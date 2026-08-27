"""End-to-end PAPER pipeline integration test.

Exercises the production path with no network:
    book + trades -> OrderFlowEngine (SHARED with replay/live)
    -> SignalEngine/EventDetector (raw direction)
    -> RiskEngine.pre_trade (guards)
    -> PaperExecution / OrderStateManager (paper fill + duplicate protection)
    -> Journal (audit trail)

This mirrors app.main.py's live loop using the same OrderFlowEngine that
app.replay.py uses, confirming a single feature/signal pipeline across paths.
"""
import tempfile
from pathlib import Path

from app.orderbook import LocalOrderBook
from app.models import DepthEvent, TradeEvent
from app.features import OrderFlowEngine
from app.signal import SignalEngine
from app.events import EventDetector
from app.risk import RiskEngine
from app.execution import PaperExecution, OrderStateManager
from app.journal import Journal


def _seeded_book():
    b = LocalOrderBook(20)
    bids = [[100.0 - i * 0.01, 5.0] for i in range(5)]   # 25 lots bid side
    asks = [[100.01 + i * 0.01, 1.0] for i in range(5)]  # 5 lots ask side
    b.load_snapshot(bids, asks, 1000)
    b.state.synchronized = True
    b.state.last_event_ms = 1_000_000
    return b


def _run_pipeline(book, flow, now):
    flow.on_book_event(DepthEvent(now, 1001, 1001,
                                  [(100.0, 5.0)], [(100.01, 1.0)]))
    for i in range(20):
        # all aggressive BUY -> positive delta + imbalance already positive
        flow.on_trade(TradeEvent(now - (20 - i) * 100, now, 100.005, 1.0, buyer_is_maker=False))
    f = flow.snapshot(now_ms=now)
    sig = SignalEngine().decide(f, EventDetector().detect(f))
    risk = RiskEngine()
    rd = risk.pre_trade(equity=100_000, entry=f.mid, stop=f.mid * 0.99,
                        spread_bps=f.spread_bps,
                        last_event_ms=book.state.last_event_ms, now_ms=now,
                        connected=True)
    mgr = OrderStateManager()
    ex = PaperExecution(mgr)
    jpath = Path(tempfile.mkdtemp()) / "journal.jsonl"
    journal = Journal(path=str(jpath))
    if sig.action in ("BUY", "SELL") and rd.allowed:
        r = ex.submit("BTCUSDT", sig.action, rd.qty, f.mid,
                      client_id="o1", book=book)
        journal.write({"type": "decision", "action": sig.action,
                       "risk_ok": True, "fill": r.status})
    else:
        journal.write({"type": "decision", "action": "NO_TRADE",
                       "signal": sig.action, "risk_ok": rd.allowed,
                       "reason": sig.reason})
    return f, sig, rd, mgr, ex, journal


def test_end_to_end_paper_pipeline_runs_and_executes():
    book = _seeded_book()
    flow = OrderFlowEngine(book)
    f, sig, rd, mgr, ex, journal = _run_pipeline(book, flow, 1_000_000)
    # Raw order-flow signal should be BUY (positive delta + positive imbalance)
    assert sig.action == "BUY"
    assert rd.allowed
    # Paper order filled at touch (best ask)
    lines = journal.path.read_text().splitlines()
    assert len(lines) == 1
    rec = __import__("json").loads(lines[0])
    assert rec["action"] == "BUY"
    assert rec["fill"] == "PAPER_FILLED"
    assert mgr.get("ORD-1").status == "FILLED"


def test_pipeline_duplicate_order_protection():
    book = _seeded_book()
    flow = OrderFlowEngine(book)
    f, sig, rd, mgr, ex, journal = _run_pipeline(book, flow, 1_000_000)
    # Second submit with same client_id must be rejected (duplicate protection)
    r2 = ex.submit("BTCUSDT", "BUY", rd.qty, f.mid, client_id="o1", book=book)
    assert r2.status == "REJECTED_DUPLICATE"
    assert len(mgr.open_orders) == 0  # first was filled, second rejected


def test_pipeline_emergency_close_blocks_pretrade():
    book = _seeded_book()
    flow = OrderFlowEngine(book)
    now = 1_000_000
    flow.on_book_event(DepthEvent(now, 1001, 1001, [(100.0, 5.0)], [(100.01, 1.0)]))
    for i in range(20):
        flow.on_trade(TradeEvent(now - (20 - i) * 100, now, 100.005, 1.0, buyer_is_maker=False))
    f = flow.snapshot(now_ms=now)
    risk = RiskEngine()
    risk.trigger_emergency("integration test")
    rd = risk.pre_trade(equity=100_000, entry=f.mid, stop=f.mid * 0.99,
                        spread_bps=f.spread_bps,
                        last_event_ms=book.state.last_event_ms, now_ms=now,
                        connected=True)
    assert not rd.allowed
    assert "EMERGENCY" in rd.reason


def test_pipeline_stale_data_blocks_pretrade():
    book = _seeded_book()
    flow = OrderFlowEngine(book)
    now = 5_000_000  # book last_event_ms is 1_000_000 -> very stale
    risk = RiskEngine()
    rd = risk.pre_trade(equity=100_000, entry=100.0, stop=99.0,
                        spread_bps=1.0,
                        last_event_ms=book.state.last_event_ms, now_ms=now,
                        connected=True)
    assert not rd.allowed
    assert "stale" in rd.reason.lower()
