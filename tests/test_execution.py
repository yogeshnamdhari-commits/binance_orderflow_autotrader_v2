"""Tests for the execution / order-state layer (app.execution)."""
from app.execution import OrderStateManager, PaperExecution, LiveExecution
from app.orderbook import LocalOrderBook


def _book():
    b = LocalOrderBook(10)
    b.load_snapshot([[100.0, 2.0]], [[101.0, 2.0]], 1)
    b.state.synchronized = True
    return b


def test_duplicate_client_id_rejected():
    m = OrderStateManager()
    o1 = m.create("BTCUSDT", "BUY", 1.0, 100.0, client_id="c1")
    assert o1 is not None
    o2 = m.create("BTCUSDT", "BUY", 1.0, 100.0, client_id="c1")
    assert o2 is None  # duplicate-order protection


def test_fill_transitions_to_filled():
    m = OrderStateManager()
    o = m.create("BTCUSDT", "BUY", 1.0, 100.0, client_id="c1")
    m.mark_filled(o.order_id, 100.5, 1.0)
    assert m.get(o.order_id).status == "FILLED"
    assert m.get(o.order_id).avg_fill_price == 100.5


def test_emergency_close_all():
    m = OrderStateManager()
    m.create("BTCUSDT", "BUY", 1.0, 100.0, client_id="c1")
    m.create("BTCUSDT", "SELL", 1.0, 100.0, client_id="c2")
    closed = m.emergency_close_all("test")
    assert len(closed) == 2
    assert m.open_orders == []


def test_paper_execution_fills_at_touch_and_rejects_duplicate():
    mgr = OrderStateManager()
    ex = PaperExecution(mgr)
    book = _book()
    r1 = ex.submit("BTCUSDT", "BUY", 1.0, 100.0, client_id="c1", book=book)
    assert r1.status == "PAPER_FILLED"
    # buy fills at best ask = 101.0
    assert mgr.get(r1.order_id).avg_fill_price == 101.0
    r2 = ex.submit("BTCUSDT", "BUY", 1.0, 100.0, client_id="c1", book=book)
    assert r2.status == "NO_TRADE" or r2.status == "REJECTED_DUPLICATE"


def test_live_execution_locked():
    ex = LiveExecution(client=None)
    try:
        ex.submit("BTCUSDT", "BUY", 1.0, 100.0)
        assert False, "live execution must remain locked"
    except RuntimeError as e:
        assert "locked" in str(e).lower() or "OFF" in str(e)
