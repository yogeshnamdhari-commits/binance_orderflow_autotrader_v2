from app.mm.live_pnl import Fill, LivePnL


def test_long_round_trip_realized_pnl_and_fee():
    pnl = LivePnL()
    assert pnl.apply_fill(Fill("t1", "BUY", 1.0, 100.0, 0.1))
    assert pnl.apply_fill(Fill("t2", "SELL", 1.0, 101.0, 0.1))
    snap = pnl.snapshot(101.0)
    assert snap.position_qty == 0.0
    assert snap.realized_pnl_usd == 1.0
    assert snap.fees_usd == 0.2
    assert snap.net_pnl_usd == 0.8


def test_short_mark_to_market():
    pnl = LivePnL()
    pnl.apply_fill(Fill("t1", "SELL", 2.0, 100.0, 0.0))
    snap = pnl.snapshot(97.0)
    assert snap.position_qty == -2.0
    assert snap.inventory_mtm_usd == 6.0
    assert snap.net_pnl_usd == 6.0


def test_duplicate_trade_id_is_ignored():
    pnl = LivePnL()
    assert pnl.apply_fill(Fill("t1", "BUY", 1.0, 100.0, 0.0))
    assert not pnl.apply_fill(Fill("t1", "BUY", 1.0, 100.0, 0.0))
    assert pnl.position_qty == 1.0
