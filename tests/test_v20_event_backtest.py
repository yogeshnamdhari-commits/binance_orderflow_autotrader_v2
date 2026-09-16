from app.mm.book import L2Snapshot, L2Update
from app.mm.config import V20Config
from app.mm.event_backtest import run_event_backtest
from app.mm.execution_replay import Side, TradeEvent


def test_event_backtest_uses_observed_trades_and_fees():
    snapshot = L2Snapshot(
        timestamp_ns=0,
        last_update_id=0,
        bids=[(99.0, 10.0), (98.0, 10.0)],
        asks=[(101.0, 10.0), (102.0, 10.0)],
    )
    depth = [
        L2Update(1_000, 1, 1, 0, [], []),
        L2Update(2_000, 2, 2, 1, [(99.1, 10.0)], [(100.9, 10.0)]),
        L2Update(3_000_000, 3, 3, 2, [], []),
        L2Update(4_000_000, 4, 4, 3, [], []),
    ]
    trades = [
        TradeEvent(1_500, 99.0, 0.5, Side.SELL, 1),
        TradeEvent(1_600, 101.0, 0.5, Side.BUY, 2),
    ]
    config = V20Config(
        base_half_spread_bps=2.5,
        max_half_spread_bps=4.0,
        quote_size_usd=50.0,
        maker_fee_bps=1.0,
        inventory_penalty_bps=2.0,
    )

    result = run_event_backtest(snapshot, depth, trades, config, horizon_ms=(1, 5, 10))

    assert result.fills == 2
    assert result.filled_qty > 0
    assert result.fees_usd > 0
    assert result.final_inventory != 0 or result.fills == 2
    assert set(result.as_by_horizon) == {1, 5, 10}
