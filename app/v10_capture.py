"""CLI for research-only Binance USDⓈ-M public market-data capture.

This module has no authentication and no order-placement capability.
"""
from __future__ import annotations

import argparse
import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

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
    """Fetch a REST depth snapshot from Binance USDⓈ-M futures API."""
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
    """Find the first depthUpdate event that bridges the REST snapshot."""
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

    state: dict[str, object] = {
        "snapshot_id": None,
        "bridge_found": False,
        "snapshot_fetched": False,
        "bridge_deadline": None,
        "buffered": [],
        "closed_by_deadline": False,
    }
    deadline = time.monotonic() + duration_seconds
    snapshot_lock = threading.Lock()

    def fetch_snapshot_and_find_bridge() -> None:
        with snapshot_lock:
            if state["snapshot_fetched"]:
                return
            try:
                snap = fetch_rest_snapshot(symbol.upper())
                snapshot_id = int(snap["lastUpdateId"])
                (session_dir / "snapshot.json").write_text(
                    json.dumps(snap, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                state["snapshot_id"] = snapshot_id
                state["snapshot_fetched"] = True
                first_bridge = find_bridging_index(state["buffered"], snapshot_id)
                if first_bridge is not None:
                    state["bridge_found"] = True
                    recorder.record_bootstrap(snapshot_id, first_bridge, state["buffered"])
                    for idx in range(first_bridge, len(state["buffered"])):
                        raw, ns, st = state["buffered"][idx]
                        recorder.handle_message(raw, receive_ns=ns)
                    state["buffered"].clear()
                else:
                    state["bridge_deadline"] = time.monotonic() + 5.0
            except Exception as exc:
                recorder.record_bootstrap_failure(-1, "SNAPSHOT_FETCH_FAILED", str(exc))
                _ws.close()

    def on_message(_ws, message) -> None:
        receive_ns = time.time_ns()

        try:
            parsed = json.loads(message)
        except Exception:
            return

        stream = parsed.get("stream") if isinstance(parsed, dict) else None

        if not state["bridge_found"]:
            state["buffered"].append((message, receive_ns, stream))
            if state["snapshot_fetched"] and state["snapshot_id"] is not None:
                first_bridge = find_bridging_index(state["buffered"], state["snapshot_id"])
                if first_bridge is not None:
                    state["bridge_found"] = True
                    recorder.record_bootstrap(state["snapshot_id"], first_bridge, state["buffered"])
                    for idx in range(first_bridge, len(state["buffered"])):
                        raw, ns, st = state["buffered"][idx]
                        recorder.handle_message(raw, receive_ns=ns)
                    state["buffered"].clear()
                elif state["bridge_deadline"] is not None and time.monotonic() > state["bridge_deadline"]:
                    recorder.record_bootstrap_failure(
                        state["snapshot_id"],
                        "BRIDGE_TIMEOUT",
                        "No depthUpdate satisfying U <= snapshot_id+1 <= u found within bootstrap window",
                    )
                    _ws.close()
            return

        recorder.handle_message(message, receive_ns=receive_ns)
        if time.monotonic() >= deadline:
            _ws.close()

    def on_error(_ws, _error) -> None:
        recorder.mark_reconnect()

    def on_close(_ws, _status_code, _message) -> None:
        if not state["bridge_found"] and not state["snapshot_fetched"]:
            recorder.record_bootstrap_failure(
                state["snapshot_id"] if state["snapshot_id"] is not None else -1,
                "CAPTURE_CLOSED",
                "WebSocket closed before snapshot was fetched",
            )
        elif not state["bridge_found"]:
            recorder.record_bootstrap_failure(
                state["snapshot_id"],
                "BRIDGE_TIMEOUT",
                "No depthUpdate satisfying U <= snapshot_id+1 <= u found within bootstrap window",
            )
        recorder.close()

    socket = websocket.WebSocketApp(
        ws_url,
        on_open=lambda _ws: None,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    def force_close_at_deadline() -> None:
        remaining = max(0.0, deadline - time.monotonic())
        time.sleep(remaining)
        state["closed_by_deadline"] = True
        socket.close()

    deadline_thread = threading.Thread(target=force_close_at_deadline, daemon=True)
    deadline_thread.start()

    snapshot_thread = threading.Thread(
        target=lambda: (
            time.sleep(5.0),
            fetch_snapshot_and_find_bridge(),
        ),
        daemon=True,
    )
    snapshot_thread.start()

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
