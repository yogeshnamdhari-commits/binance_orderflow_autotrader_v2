from app.v19.data_ingest import normalize_binance_depth_row, normalize_binance_trade_row, split_time_ranges


def test_normalize_binance_depth_row():
    row = {
        "symbol": "BTCUSDT",
        "time": "1788822007000",
        "first_update_id": "10",
        "last_update_id": "10",
        "side": "b",
        "update_type": "delta",
        "price": "100.0",
        "qty": "1.25",
    }
    normalized = normalize_binance_depth_row(row)
    assert normalized == {
        "type": "depth",
        "ts_ms": 1788822007000,
        "first_update_id": 10,
        "last_update_id": 10,
        "side": "b",
        "update_type": "delta",
        "price": 100.0,
        "qty": 1.25,
    }


def test_normalize_binance_trade_row():
    row = {
        "time": "1788822007010",
        "price": "100.1",
        "qty": "0.5",
        "is_buyer_maker": "true",
    }
    normalized = normalize_binance_trade_row(row)
    assert normalized == {
        "type": "trade",
        "ts_ms": 1788822007010,
        "price": 100.1,
        "qty": 0.5,
        "buyer_is_maker": True,
    }


def test_split_time_ranges_respects_seven_day_binance_limit():
    ranges = split_time_ranges(0, 15 * 24 * 60 * 60 * 1000)
    assert ranges == [
        (0, 7 * 24 * 60 * 60 * 1000 - 1),
        (7 * 24 * 60 * 60 * 1000, 14 * 24 * 60 * 60 * 1000 - 1),
        (14 * 24 * 60 * 60 * 1000, 15 * 24 * 60 * 60 * 1000),
    ]
