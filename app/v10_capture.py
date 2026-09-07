"""CLI for research-only Binance USDⓈ-M public market-data capture.

This module has no authentication and no order-placement capability.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import urllib.request

from .v10_recorder import V10Recorder

DEFAULT_WS = "wss://fstream.binance.com"
DEFAULT_STREAMS = ["btcusdt@depth@100ms", "btcusdt@trade", "btcusdt@bookTicker"]
REST_DEPTH_BASE = "https://fapi.binance.com/fapi/v1/depth"


def build_ws_url(base_url: str, streams: list[str]) -> str:
    if not streams:
        raise ValueError("at least one stream is required")
    stream_str = "/".join(streams)
    return f"{base_url}/stream?streams={stream_str}"


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


def fetch_rest_snapshot(symbol: str, limit: int = 1000) -> dict[str, object]:
    """Fetch a REST depth snapshot from Binance USDⓈ-M futures API.

    Returns the parsed JSON snapshot with keys: lastUpdateId, bids, asks,
    E (event time), T (transaction time), s (symbol), t (trade time).
    """
    symbol = symbol.upper()
    url = f"{REST_DEPTH_BASE}?symbol={symbol}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "v10-research-capture/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _depth_update_id_range(raw_json: str) -> tuple[int, int] | None:
    """Extract (U, u) from a depthUpdate event raw JSON string."""
    try:
        payload = json.loads(raw_json)
        data = payload.get("data", payload)
        U = int(data["U"])
        u = int(data["u"])
        return U, u
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def find_bridging_index(
    buffered_events: list[tuple[str, int, str | None]], snapshot_id: int
) -> int | None:
    """Find the first depthUpdate event that bridges the REST snapshot.

    A depthUpdate bridges the snapshot when U <= snapshot_id + 1 <= u.
    Returns the index into buffered_events, or None if no bridge found.
    """
    for idx, item in enumerate(buffered_events):
        raw_json = item[0]
        range_result = _depth_update_id_range(raw_json)
        if range_result is None:
            continue
        U, u = range_result
        if U <= snapshot_id + 1 <= u:
            return idx
    return None


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

    import websocket

    snapshot = fetch_rest_snapshot(symbol.upper())
    snapshot_id = int(snapshot["lastUpdateId"])
    (session_dir / "snapshot.json").write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    # Buffer WebSocket events until a bridging depthUpdate is found, then
    # flush the buffer (minus pre-bridge events) to the recorder. This follows
    # Binance's documented diff-depth synchronization protocol.
    buffered: list[tuple[str, int]] = []
    bridge_found = False
    first_event_ts: float | None = None
    deadline = time.monotonic() + duration_seconds

    def on_message(_ws, message):
        nonlocal bridge_found, first_event_ts
        receive_ns = time.time_ns()
        if first_event_ts is None:
            first_event_ts = time.monotonic()

        try:
            parsed = json.loads(message)
        except Exception:
            return

        stream = parsed.get("stream") if isinstance(parsed, dict) else None

        if not bridge_found:
            buffered.append((message, receive_ns, stream))
            first_bridge = find_bridging_index(buffered, snapshot_id)
            if first_bridge is not None:
                bridge_found = True
                for idx in range(first_bridge, len(buffered)):
                    raw, ns, st = buffered[idx]
                    recorder.handle_message(raw, receive_ns=ns)
                buffered.clear()
            elif time.monotonic() - first_event_ts > 2.0 and buffered:
                first_event = _depth_update_id_range(buffered[0][0])
                if first_event is not None:
                    U, u = first_event
                    if u > snapshot_id:
                        bridge_found = True
                        for idx in range(len(buffered)):
                            raw, ns, st = buffered[idx]
                            recorder.handle_message(raw, receive_ns=ns)
                        buffered.clear()
            return

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
