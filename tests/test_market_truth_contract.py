from app.mm.market_truth import SymbolTruth, TruthStatus, invalid, ok_metric, unavailable


def test_missing_required_metric_blocks_signal():
    now = 1_000_000
    s = SymbolTruth("BTCUSDT")
    s.book_synchronized = True
    s.book_sequence_ok = True
    s.trade_stream_ok = True
    s.market_stream_ok = True
    s.price = ok_metric(100, source="trade", exchange_ts_ms=now, receive_ts_ms=now, max_age_ms=1000)
    s.open_interest = unavailable("openInterest_rest", "not acquired")
    allowed, reasons = s.gate(now, required=["price", "open_interest"])
    assert allowed is False
    assert "OPEN_INTEREST_UNAVAILABLE" in reasons


def test_invalid_never_becomes_zero():
    metric = invalid("binance_depth", "crossed_book")
    assert metric.status == TruthStatus.INVALID
    assert metric.value is None


def test_stale_metric_blocks_signal():
    now = 1_000_000
    s = SymbolTruth("BTCUSDT")
    s.book_synchronized = True
    s.book_sequence_ok = True
    s.trade_stream_ok = True
    s.market_stream_ok = True
    s.price = ok_metric(100, source="trade", exchange_ts_ms=now - 5000, receive_ts_ms=now, max_age_ms=1000)
    allowed, reasons = s.gate(now, required=["price"])
    assert allowed is False
    assert "PRICE_STALE" in reasons


def test_force_no_trade_is_explicit():
    now = 1_000_000
    s = SymbolTruth("BTCUSDT")
    s.force_no_trade(now, "OPEN_INTEREST_UNAVAILABLE")
    assert s.signal.value == "NO_TRADE"
    assert s.signal_authority == "DATA_GATE"
    assert s.signal.status == TruthStatus.OK
