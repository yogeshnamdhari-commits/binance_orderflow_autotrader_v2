"""CLI for research-only Binance USDⓈ-M public market-data capture.

This module has no authentication and no order-placement capability.
"""
from __future__ import annotations

import argparse
import re
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .v10_recorder import V10Recorder

DEFAULT_WS = "wss://fstream.binance.com/stream"
DEFAULT_STREAMS = ["btcusdt@depth@100ms", "btcusdt@trade", "btcusdt@bookTicker"]


def build_ws_url(base_url: str, streams: list[str]) -> str:
    if not streams:
        raise ValueError("at least one stream is required")
    parts = urlsplit(base_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["streams"] = "/".join(streams)
    query["timeUnit"] = "MICROSECOND"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def parse_duration_seconds(value: str) -> int:
    match = re.fullmatch(r"(\d+)([smh])", value.strip().lower())
    if not match:
        raise ValueError("duration must be a positive integer followed by s, m, or h")
    amount = int(match.group(1))
    if amount <= 0:
        raise ValueError("duration must be positive")
    multiplier = {"s": 1, "m": 60, "h": 3600}[match.group(2)]
    return amount * multiplier


def capture_output_path(root: str | Path, session_id: str) -> Path:
    return Path(root) / session_id


def run_capture(symbol: str, output_dir: str | Path, duration_seconds: int, ws_base: str = DEFAULT_WS) -> Path:
    symbol = symbol.lower()
    streams = [s.replace("btcusdt", symbol, 1) for s in DEFAULT_STREAMS]
    ws_url = build_ws_url(ws_base, streams)
    recorder = V10Recorder(
        symbol=symbol,
        output_dir=output_dir,
        ws_url=ws_url,
        streams=streams,
    )
    session_dir = recorder.start()

    # Import lazily so unit tests do not require a network connection.
    import websocket

    deadline = time.monotonic() + duration_seconds

    def on_message(_ws, message):
        recorder.handle_message(message)
        if time.monotonic() >= deadline:
            _ws.close()

    def on_error(_ws, _error):
        recorder.mark_reconnect()

    def on_close(_ws, _status_code, _message):
        recorder.close()

    socket = websocket.WebSocketApp(
        ws_url,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    try:
        socket.run_forever()
    finally:
        recorder.close()
    return session_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture public Binance USDⓈ-M market data for V10 research")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--duration", default="60s")
    parser.add_argument("--output", default="data/v10")
    parser.add_argument("--ws-base", default=DEFAULT_WS)
    args = parser.parse_args()
    run_capture(args.symbol, args.output, parse_duration_seconds(args.duration), args.ws_base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
