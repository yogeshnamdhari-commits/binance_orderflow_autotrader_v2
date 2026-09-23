from app.mm.book import L2Snapshot, L2Update, OrderBook
from app.mm.config import V20Config
from app.mm.event_backtest import run_event_backtest
from app.mm.execution_replay import Side, TradeEvent


def test_event_backtest_uses_observed_trades_and_fees():
    snapshot = L2Snapshot(
        timestamp_ns=0,
        last_update_id=0,
        bids=[(99.99, 10.0)],
        asks=[(100.01, 10.0)],
        bridge_complete=True,
    )
    depth = [
        L2Update(1_000, 1, 1, 0, [], []),
        L2Update(2_000, 2, 2, 1, [(99.99, 10.0)], [(100.01, 10.0)]),
        L2Update(3_000_000, 3, 3, 2, [], []),
        L2Update(4_000_000, 4, 4, 3, [], []),
    ]
    trades = [
        TradeEvent(1_500, 99.975, 0.5, Side.SELL, 1),
        TradeEvent(1_600, 100.025, 0.5, Side.BUY, 2),
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
    assert result.quote_crossings_detected == 0
    assert result.gross_spread_capture_usd > 0
    assert result.adverse_selection_usd >= 0
    assert result.execution_effects_usd == 0


def test_crossing_quotes_are_suppressed_not_clamped():
    snapshot = L2Snapshot(
        timestamp_ns=0,
        last_update_id=0,
        bids=[(99.99, 10.0)],
        asks=[(100.01, 10.0)],
        bridge_complete=True,
    )
    depth = [L2Update(1_000, 1, 1, 0, [], [])]
    trades = [
        TradeEvent(1_500, 100.00, 1.0, Side.BUY, 1),
    ]
    config = V20Config(
        base_half_spread_bps=0.5,
        max_half_spread_bps=1.0,
        quote_size_usd=50.0,
        maker_fee_bps=1.0,
        inventory_penalty_bps=2.0,
        microprice_skew_bps=2.0,
    )

    result = run_event_backtest(snapshot, depth, trades, config)

    assert result.quote_crossings_detected > 0
    assert result.quote_crossings_suppressed > 0
    assert result.fills == 0


def test_order_book_accepts_bridge_ending_at_snapshot_id():
    snapshot = L2Snapshot(
        timestamp_ns=0,
        last_update_id=100,
        bids=[(99.99, 10.0)],
        asks=[(100.01, 10.0)],
    )
    book = OrderBook.from_snapshot(snapshot)

    bridge = L2Update(
        timestamp_ns=1_000,
        first_update_id=95,
        final_update_id=100,
        prev_final_update_id=94,
        bids=[],
        asks=[],
    )
    book.apply_update(bridge)

    # The bridge establishes continuity but contains no post-snapshot updates.
    assert book.last_update_id == 100
    assert book._awaiting_first_diff is False

    next_update = L2Update(
        timestamp_ns=2_000,
        first_update_id=101,
        final_update_id=110,
        prev_final_update_id=100,
        bids=[(99.99, 9.0)],
        asks=[(100.01, 9.0)],
    )
    book.apply_update(next_update)

    assert book.last_update_id == 110