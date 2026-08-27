"""Production-hardening failure-injection tests.

Covers: websocket disconnect, sequence gap, stale book, duplicate event,
duplicate order, order rejection, partial fill, execution timeout,
restart with open/pending position, emergency close, corrupted/missing state,
API/network failure, idempotent retry, and max-concurrent-positions guard.
"""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from app.orderbook import LocalOrderBook
from app.models import DepthEvent, TradeEvent
from app.features import OrderFlowEngine, FlowFeatures
from app.decision import DecisionEngine, DecisionState
from app.risk import RiskEngine
from app.execution import (OrderStateManager, PaperExecution, SimulatedExchange,
                          ExecutionResult)
from app.binance_feed import BinanceMarketFeed


# ----------------------------------------------------------------------
# Feed / market-data integrity
# ----------------------------------------------------------------------
def test_websocket_disconnect_marks_book_not_ready():
    cfg = SimpleNamespace(rest="https://x", ws="wss://x")
    book = LocalOrderBook(10)
    flow = OrderFlowEngine(book)
    cb = []
    feed = BinanceMarketFeed(cfg, "btcusdt", book, flow, status_cb=cb.append)
    feed.ready = True
    feed.on_close(None)
    assert feed.ready is False
    assert any(s.get("status") == "CLOSED" for s in cb)


def test_api_network_failure_logged_not_crashed():
    cfg = SimpleNamespace(rest="https://x", ws="wss://x")
    book = LocalOrderBook(10)
    flow = OrderFlowEngine(book)
    cb = []
    feed = BinanceMarketFeed(cfg, "btcusdt", book, flow, status_cb=cb.append)
    feed.on_error(None, "boom")
    assert any(s.get("status") == "WS_ERROR" for s in cb)


def test_orderbook_large_hole_triggers_gap():
    b = LocalOrderBook(10)
    b.load_snapshot([[100.0, 1.0]], [[101.0, 1.0]], 1000)
    # first event establishes sync normally
    assert b.apply(DepthEvent(1, 1001, 1001, [(100.0, 1.0)], [(101.0, 1.0)])) == "OK"
    # subsequent event with a >5000 hole -> GAP
    assert b.apply(DepthEvent(2, 7000, 7000, [(100.0, 1.0)], [(101.0, 1.0)])) == "GAP"
    assert b.state.synchronized is False


def test_duplicate_depth_event_is_stale():
    b = LocalOrderBook(10)
    b.load_snapshot([[100.0, 1.0]], [[101.0, 1.0]], 1000)
    ev = DepthEvent(1, 1001, 1001, [(100.0, 1.0)], [(101.0, 1.0)])
    assert b.apply(ev) == "OK"
    # replaying the same event (final_update_id <= last) is dropped as STALE
    assert b.apply(ev) == "STALE"


def test_stale_book_blocks_decision():
    b = LocalOrderBook(10)
    b.load_snapshot([[100.0, 1.0]], [[101.0, 1.0]], 1000)  # synchronized=False
    flow = OrderFlowEngine(b)
    f = flow.snapshot(now_ms=1_000_000)
    d = DecisionEngine(fill_model=None).evaluate(f)
    assert d.state == DecisionState.INVALID_DATA


# ----------------------------------------------------------------------
# Execution safety
# ----------------------------------------------------------------------
def test_duplicate_order_rejected():
    m = OrderStateManager()
    ex = PaperExecution(m)
    r1 = ex.submit("BTCUSDT", "BUY", 1.0, 100.0, client_id="c1")
    assert r1.status == "PAPER_FILLED"
    r2 = ex.submit("BTCUSDT", "BUY", 1.0, 100.0, client_id="c1")
    assert r2.status == "REJECTED_DUPLICATE"
    assert len(m._orders) == 1


def test_order_rejection_transitions_state():
    m = OrderStateManager()
    ex = SimulatedExchange(m, mode="reject")
    r = ex.submit("BTCUSDT", "BUY", 1.0, 100.0, client_id="c1")
    assert r.status == "REJECTED"
    assert m.get(r.order_id).status == "REJECTED"


def test_partial_fill_accumulates_to_filled():
    m = OrderStateManager()
    o = m.create("BTCUSDT", "BUY", 2.0, 100.0, client_id="c1")
    m.mark_partial_fill(o.order_id, 100.0, 1.0)
    assert m.get(o.order_id).status == "PARTIAL"
    m.mark_filled(o.order_id, 100.0, 1.0)
    assert m.get(o.order_id).status == "FILLED"
    assert m.get(o.order_id).filled_qty == 2.0


def test_execution_timeout_marks_dead():
    m = OrderStateManager()
    ex = SimulatedExchange(m, mode="timeout")
    r = ex.submit("BTCUSDT", "BUY", 1.0, 100.0, client_id="c1")
    assert r.status == "TIMEOUT"
    assert m.get(r.order_id).status == "TIMEOUT"


def test_idempotent_retry_after_rejection_no_duplicate():
    m = OrderStateManager()
    ex = SimulatedExchange(m, mode="reject")
    ex.submit("BTCUSDT", "BUY", 1.0, 100.0, client_id="c1")  # rejected
    r2 = ex.submit("BTCUSDT", "BUY", 1.0, 100.0, client_id="c1")  # retry
    assert r2.status == "REJECTED_DUPLICATE"
    assert len(m._orders) == 1  # no second order created


def test_emergency_close_all_orders():
    m = OrderStateManager()
    m.create("BTCUSDT", "BUY", 1.0, 100.0, client_id="c1")
    m.create("BTCUSDT", "SELL", 1.0, 100.0, client_id="c2")
    closed = m.emergency_close_all("test")
    assert len(closed) == 2
    assert m.open_orders == []


# ----------------------------------------------------------------------
# Restart / state recovery (paper-grade)
# ----------------------------------------------------------------------
def test_restart_with_open_position_recovers_state():
    p = Path(tempfile.mkdtemp()) / "orders.json"
    m1 = OrderStateManager()
    m1.create("BTCUSDT", "BUY", 1.0, 100.0, client_id="c1")  # OPEN
    m1.save(p)
    m2 = OrderStateManager()
    n = m2.load(p)
    assert n == 1
    assert len(m2.open_orders) == 1
    # duplicate client-id detection spans restart
    assert m2.duplicate("c1") is True


def test_restart_with_pending_order_then_emergency():
    p = Path(tempfile.mkdtemp()) / "orders.json"
    m1 = OrderStateManager()
    m1.create("BTCUSDT", "BUY", 1.0, 100.0, client_id="c1")  # OPEN/pending
    m1.save(p)
    m2 = OrderStateManager()
    m2.load(p)
    closed = m2.emergency_close_all("restart")
    assert len(closed) == 1
    assert m2.open_orders == []


def test_corrupted_state_loads_empty_safely():
    p = Path(tempfile.mkdtemp()) / "orders.json"
    p.write_text("{not valid json")
    m = OrderStateManager()
    assert m.load(p) == 0
    assert m.open_orders == []


def test_missing_state_loads_empty_safely():
    m = OrderStateManager()
    assert m.load(Path(tempfile.mkdtemp()) / "nope.json") == 0


# ----------------------------------------------------------------------
# Risk safety
# ----------------------------------------------------------------------
def test_max_concurrent_positions_guard():
    r = RiskEngine(max_open_orders=1)
    ok = r.pre_trade(100_000, 100.0, 99.0, 1.0, 2_000_000, 2_000_000, True,
                     new_notional=1000.0, open_orders=1)
    assert not ok.allowed
    assert "concurrent" in ok.reason.lower()
    ok2 = r.pre_trade(100_000, 100.0, 99.0, 1.0, 2_000_000, 2_000_000, True,
                      new_notional=1000.0, open_orders=0)
    assert ok2.allowed


def test_risk_reset_clears_state():
    r = RiskEngine()
    r.trigger_emergency("x")
    r.daily_pnl = -50.0
    r.reset()
    assert r.emergency is False
    assert r.daily_pnl == 0.0
