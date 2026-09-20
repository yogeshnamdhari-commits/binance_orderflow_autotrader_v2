"""CLI for research-only Binance USDⓈ-M public market-data capture.

No authentication or order-placement capability is present. Snapshot bridging
uses Binance's snapshot + diff-depth rule and fails closed on ambiguity.
"""
from __future__ import annotations

import argparse
import json
import re
import threading
import time
from pathlib import Path

from .v10_recorder import V10Recorder

DEFAULT_WS = "wss://fstream.binance.com/public"
DEFAULT_STREAMS = ["btcusdt@depth@100ms", "btcusdt@trade", "btcusdt@bookTicker"]
DEPTH_REST_URL = "https://fapi.binance.com/fapi/v1/depth"
DEPTH_API_WS = "wss://ws-fapi.binance.com/ws-fapi/v1"


def build_ws_url(base_url: str, streams: list[str]) -> str:
    if not streams:
        raise ValueError("at least one stream is required")
    return f"{base_url}/stream?streams={'/'.join(streams)}"


def parse_duration_seconds(value: str) -> int:
    match = re.fullmatch(r"(\d+)([smh])", value.strip().lower())
    if not match:
        raise ValueError("duration must be a positive integer followed by s, m, or h")
    amount = int(match.group(1))
    if amount <= 0:
        raise ValueError("duration must be positive")
    return amount * {"s": 1, "m": 60, "h": 3600}[match.group(2)]


def capture_output_path(root: str | Path, session_id: str) -> Path:
    return Path(root) / session_id


def fetch_rest_snapshot(symbol: str, limit: int = 1000) -> dict[str, object]:
    import requests

    response = requests.get(
        DEPTH_REST_URL,
        params={"symbol": symbol.upper(), "limit": limit},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or "lastUpdateId" not in payload:
        raise RuntimeError(f"invalid Binance REST depth snapshot response: {payload}")
    return payload


def fetch_ws_snapshot(symbol: str, limit: int = 1000) -> dict[str, object]:
    import uuid
    import websocket

    request = {
        "id": str(uuid.uuid4()),
        "method": "depth",
        "params": {"symbol": symbol.upper(), "limit": limit},
    }
    connection = websocket.create_connection(DEPTH_API_WS, timeout=10)
    try:
        connection.send(json.dumps(request, separators=(",", ":")))
        response = json.loads(connection.recv())
    finally:
        connection.close()

    if response.get("status") != 200:
        raise RuntimeError(f"Binance WS depth snapshot failed: {response}")
    result = response.get("result")
    if not isinstance(result, dict) or "lastUpdateId" not in result:
        raise RuntimeError(f"invalid Binance WS depth snapshot response: {response}")
    return result


def fetch_ws_snapshot_with_retries(
    symbol: str,
    *,
    limit: int = 1000,
    attempts: int = 3,
    retry_delay_seconds: float = 1.0,
) -> dict[str, object]:
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fetch_ws_snapshot(symbol, limit=limit)
        except Exception as exc:
            last_error = exc
            if attempt < attempts and retry_delay_seconds > 0:
                time.sleep(retry_delay_seconds)
    assert last_error is not None
    raise last_error


def fetch_snapshot_with_fallback(
    symbol: str,
    *,
    limit: int = 1000,
) -> tuple[dict[str, object], str]:
    try:
        return (
            fetch_rest_snapshot_with_retries(
                symbol.upper(), limit=limit, attempts=2, retry_delay_seconds=0.5
            ),
            "REST",
        )
    except Exception as rest_error:
        try:
            return (
                fetch_ws_snapshot_with_retries(
                    symbol.upper(), limit=limit, attempts=3, retry_delay_seconds=0.5
                ),
                "WS_API",
            )
        except Exception as ws_error:
            raise RuntimeError(
                f"snapshot_acquisition_failed: REST={type(rest_error).__name__}:{rest_error}; "
                f"WS_API={type(ws_error).__name__}:{ws_error}"
            ) from ws_error


def fetch_rest_snapshot_with_retries(
    symbol: str,
    *,
    limit: int = 1000,
    attempts: int = 3,
    retry_delay_seconds: float = 1.0,
) -> dict[str, object]:
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fetch_rest_snapshot(symbol, limit=limit)
        except Exception as exc:
            last_error = exc
            if attempt < attempts and retry_delay_seconds > 0:
                time.sleep(retry_delay_seconds)
    assert last_error is not None
    raise last_error


def _depth_update_id_range(raw_json: str) -> tuple[int, int] | None:
    try:
        payload = json.loads(raw_json)
        data = payload.get("data", payload)
        return int(data["U"]), int(data["u"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def find_bridging_index(
    buffered_events: list[tuple[str, int, str | None]], snapshot_id: int
) -> int | None:
    """Find first diff event satisfying U <= snapshot_id+1 <= u."""
    expected = int(snapshot_id) + 1
    for idx, item in enumerate(buffered_events):
        seq = _depth_update_id_range(item[0])
        if seq is None:
            continue
        U, u = seq
        if U <= expected <= u:
            return idx
    return None


def run_capture(
    symbol: str,
    output_dir: str | Path,
    duration_seconds: int,
    ws_base: str = DEFAULT_WS,
) -> Path:
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
        "snapshot_source": "REST",
        "bridge_found": False,
        "snapshot_fetched": False,
        "bridge_deadline": None,
        "buffered": [],
    }
    deadline = time.monotonic() + duration_seconds
    snapshot_lock = threading.Lock()

    def close_socket() -> None:
        socket.close()

    def fetch_snapshot_and_find_bridge() -> None:
        with snapshot_lock:
            if state["snapshot_fetched"] or state["bridge_found"]:
                return
            try:
                snap, snapshot_source = fetch_snapshot_with_fallback(
                    symbol.upper(), limit=1000
                )
                state["snapshot_source"] = snapshot_source
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
                    buffered_to_replay = list(state["buffered"])
                    state["buffered"].clear()
                    recorder.record_bootstrap(
                        snapshot_id,
                        first_bridge,
                        buffered_to_replay,
                        snapshot_source=str(state["snapshot_source"]),
                    )
                    for raw, ns, _stream in buffered_to_replay[first_bridge:]:
                        recorder.handle_message(raw, receive_ns=ns)
                else:
                    state["bridge_deadline"] = time.monotonic() + 5.0
            except Exception as exc:
                recorder.record_bootstrap_failure(-1, "SNAPSHOT_FETCH_FAILED", str(exc))
                close_socket()

    def on_message(_ws, message) -> None:
        receive_ns = time.time_ns()
        try:
            parsed = json.loads(message)
        except Exception:
            return
        stream = parsed.get("stream") if isinstance(parsed, dict) else None

        with snapshot_lock:
            if not state["bridge_found"]:
                state["buffered"].append((message, receive_ns, stream))
                if state["snapshot_fetched"] and state["snapshot_id"] is not None:
                    first_bridge = find_bridging_index(
                        state["buffered"], int(state["snapshot_id"])
                    )
                    if first_bridge is not None:
                        state["bridge_found"] = True
                        buffered_to_replay = list(state["buffered"])
                        state["buffered"].clear()
                        recorder.record_bootstrap(
                            int(state["snapshot_id"]),
                            first_bridge,
                            buffered_to_replay,
                        )
                        for raw, ns, _stream in buffered_to_replay[first_bridge:]:
                            recorder.handle_message(raw, receive_ns=ns)
                        return
                    if (
                        state["bridge_deadline"] is not None
                        and time.monotonic() > state["bridge_deadline"]
                    ):
                        recorder.record_bootstrap_failure(
                            int(state["snapshot_id"]),
                            "BRIDGE_TIMEOUT",
                            "No depthUpdate satisfying U <= snapshot_id+1 <= u found",
                        )
                        close_socket()
                        return
                else:
                    return

        recorder.handle_message(message, receive_ns=receive_ns)
        if time.monotonic() >= deadline:
            close_socket()

    def on_error(_ws, _error) -> None:
        recorder.mark_reconnect()

    def on_close(_ws, _status_code, _message) -> None:
        if not state["bridge_found"] and not state["snapshot_fetched"]:
            recorder.record_bootstrap_failure(
                int(state["snapshot_id"]) if state["snapshot_id"] is not None else -1,
                "CAPTURE_CLOSED",
                "WebSocket closed before snapshot was fetched",
            )
        elif not state["bridge_found"]:
            recorder.record_bootstrap_failure(
                int(state["snapshot_id"]),
                "BRIDGE_TIMEOUT",
                "No depthUpdate satisfying U <= snapshot_id+1 <= u found",
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
        time.sleep(max(0.0, deadline - time.monotonic()))
        close_socket()

    threading.Thread(target=force_close_at_deadline, daemon=True).start()
    threading.Thread(
        target=lambda: (time.sleep(5.0), fetch_snapshot_and_find_bridge()),
        daemon=True,
    ).start()

    try:
        socket.run_forever()
    finally:
        recorder.close()
    return session_dir


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture public Binance USDⓈ-M market data for V10 research"
    )
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--duration", default="60s")
    parser.add_argument("--output", default="data/v10")
    parser.add_argument("--ws-base", default=DEFAULT_WS)
    args = parser.parse_args()
    run_capture(args.symbol, args.output, parse_duration_seconds(args.duration), args.ws_base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
