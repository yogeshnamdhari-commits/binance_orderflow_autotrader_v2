from app.mm.book import L2Snapshot, L2Update
from app.mm.config import V20Config
from app.mm.event_backtest import run_event_backtest
from app.mm.execution_replay import Side, TradeEvent


def _config(**kwargs):
    values = dict(
        base_half_spread_bps=1.0,
        max_half_spread_bps=2.0,
        quote_size_usd=50.0,
        maker_fee_bps=0.0,
    )
    values.update(kwargs)
    return V20Config(**values)


def test_pre_quote_trade_cannot_fill_new_quote():
    snapshot = L2Snapshot(
        timestamp_ns=0,
        last_update_id=0,
        bids=[(99.0, 10.0)],
        asks=[(101.0, 10.0)],
    )
    depth = [L2Update(1_000, 1, 1, 0, [], [])]
    trades = [
        TradeEvent(500, 99.70, 1.0, Side.SELL, 1),
        TradeEvent(1_500, 99.70, 1.0, Side.SELL, 2),
    ]

    result = run_event_backtest(snapshot, depth, trades, _config())

    assert result.fills == 1


def test_toxicity_filter_suppresses_toxic_side():
    snapshot = L2Snapshot(
        timestamp_ns=0,
        last_update_id=0,
        bids=[(99.0, 100.0)],
        asks=[(101.0, 1.0)],
    )
    depth = [
        L2Update(1_000, 1, 1, 0, [], []),
        L2Update(2_000, 2, 2, 0, [], []),
    ]
    trades = [
        TradeEvent(1_500, 101.0, 50.0, Side.BUY, 1),
    ]
    result = run_event_backtest(
        snapshot,
        depth,
        trades,
        _config(
            toxicity_filter_enabled=True,
            toxicity_imbalance_threshold=0.65,
            toxicity_flow_threshold=0.60,
        ),
    )

    assert result.toxicity_suppressed_quotes == 1
