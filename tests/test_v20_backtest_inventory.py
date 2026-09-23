from app.mm.backtest import generate_quotes
from app.mm.config import V20Config


def test_inventory_skew_reduces_quotes_when_long():
    config = V20Config(
        base_half_spread_bps=2.0,
        max_half_spread_bps=4.0,
        max_position_notional_usd=10_000.0,
        inventory_penalty_bps=10.0,
    )
    flat_bid, flat_ask, _, _ = generate_quotes(100_000.0, 2.0, 0.0, config)
    long_bid, long_ask, _, _ = generate_quotes(100_000.0, 2.0, 0.10, config)

    assert long_bid < flat_bid
    assert long_ask < flat_ask


def test_inventory_skew_increases_quotes_when_short():
    config = V20Config(
        base_half_spread_bps=2.0,
        max_half_spread_bps=4.0,
        max_position_notional_usd=10_000.0,
        inventory_penalty_bps=10.0,
    )
    flat_bid, flat_ask, _, _ = generate_quotes(100_000.0, 2.0, 0.0, config)
    short_bid, short_ask, _, _ = generate_quotes(100_000.0, 2.0, -0.10, config)

    assert short_bid > flat_bid
    assert short_ask > flat_ask
