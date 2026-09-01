from pathlib import Path

from app.v10_capture import build_ws_url, parse_duration_seconds


def test_build_ws_url_uses_combined_stream_endpoint_and_microseconds():
    url = build_ws_url(
        "wss://fstream.binance.com/stream",
        ["btcusdt@depth@100ms", "btcusdt@trade", "btcusdt@bookTicker"],
    )
    assert "streams=btcusdt%40depth%40100ms%2Fbtcusdt%40trade%2Fbtcusdt%40bookTicker" in url
    assert "timeUnit=MICROSECOND" in url


def test_duration_parser_supports_seconds_minutes_hours():
    assert parse_duration_seconds("30s") == 30
    assert parse_duration_seconds("5m") == 300
    assert parse_duration_seconds("2h") == 7200


def test_duration_parser_rejects_invalid_values():
    for value in ("0s", "-1m", "5x", "abc"):
        try:
            parse_duration_seconds(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for {value}")


def test_runner_keeps_output_argument_as_a_path():
    from app.v10_capture import capture_output_path
    assert capture_output_path("data/v10", "abc") == Path("data/v10") / "abc"
