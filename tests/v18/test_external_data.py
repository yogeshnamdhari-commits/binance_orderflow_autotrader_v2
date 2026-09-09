import pytest

from app.v18.external_data import force_order_feature, parse_force_order


def test_force_order_parser_reads_market_event():
    event = parse_force_order(
        {
            "e": "forceOrder",
            "o": {
                "E": 1000,
                "s": "BTCUSDT",
                "S": "SELL",
                "o": "LIMIT",
                "p": "100.0",
                "q": "2.5",
                "ap": "99.9",
            },
        }
    )
    assert event.symbol == "BTCUSDT"
    assert event.quantity == 2.5


def test_future_force_order_is_rejected():
    event = parse_force_order(
        {"o": {"E": 1000, "s": "BTCUSDT", "S": "BUY", "o": "LIMIT", "p": "100", "q": "1", "ap": "100"}}
    )
    with pytest.raises(ValueError, match="future"):
        force_order_feature(event, now_ms=999)
