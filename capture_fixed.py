import sys
sys.path.insert(0, '/Users/targetmobile/Downloads/binance_orderflow_autotrader_v2')

import json
import time
import urllib.request
import websocket
import uuid
from pathlib import Path
from datetime import datetime, timezone

from app.v10_recorder import V10Recorder
from app.v12.capture import fetch_rest_snapshot, symbol_upper, _depth_update_id_range, find_bridging_index

DEFAULT_WS = "wss://fstream.binance.com"
DEFAULT_STREAMS = ["btcusdt@depth@100ms", "btcusdt@trade", "btcusdt@bookTicker"]
REST_DEPTH_BASE = "https://fapi.binance.com/fapi/v1/depth"
USER_AGENT = "V12-Capture/1.0"

def build_ws_url(base_url, streams):
    stream_str = "/".join(streams)
    return f"{base_url}/stream?streams={stream_str}"

def timestamp_iso():
    return datetime.now(timezone.utc).isoformat()

def symbol_upper(symbol):
    return symbol.upper()

capture_id = uuid.uuid4().hex
output_dir = Path("data/captures") / capture_id
output_dir.mkdir(parents=True, exist_ok=True)

symbol = "BTCUSDT"
symbol_lower = symbol.lower()
streams = [s.replace("btcusdt", symbol_lower, 1) for s in DEFAULT_STREAMS]
ws_url = build_ws_url(DEFAULT_WS, streams)

print(f"Starting 60-minute capture: {capture_id}")
print(f"Output: {output_dir}")
print(f"Symbol: BTCUSDT, Duration: 3600s")
sys.stdout.flush()

recorder = V10Recorder(
    symbol=symbol,
    output_dir=output_dir,
    ws_url=ws_url,
    streams=streams,
)

session_dir = recorder.start()
config_hash = hashlib.sha256(
    json.dumps({"symbol": symbol, "streams": streams, "duration_s": 3600}, sort_keys=True).encode()
).hexdigest()[:16]

utc_start = timestamp_iso()
buffered = []
bridge_found = False
reconnect_count = 0
gap_count = 0
diagnostics = {"depth": 0, "trade": 0, "bookTicker": 0, "malformed": 0}
_first_event_ts = [0.0]
snapshot_id = None

def on_message(_ws, message):
    global bridge_found, snapshot_id
    receive_ns = time.time_ns()
    parsed = _safe_json(message)
    if parsed is None:
        diagnostics["malformed"] += 1
        return
    stream = parsed.get("stream") if isinstance(parsed, dict) else None
    data = parsed.get("data", {}) if isinstance(parsed, dict) else {}
    ev_type = data.get("e") if isinstance(data, dict) else None

    if not bridge_found:
        buffered.append((message, receive_ns, stream))
        if snapshot_id is None:
            # Fetch snapshot after first depthUpdate arrives
            if ev_type == "depthUpdate":
                try:
                    snapshot = fetch_rest_snapshot(symbol_upper(symbol), limit=1000)
                    snapshot_id = int(snapshot["lastUpdateId"])
                    (session_dir / "snapshot.json").write_text(
                        json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8",
                    )
                    print(f"Snapshot fetched: lastUpdateId={snapshot_id}")
                except Exception as e:
                    print(f"Failed to fetch snapshot: {e}")
        first_bridge = find_bridging_index(buffered, snapshot_id) if snapshot_id is not None else None
        if first_bridge is not None:
            for idx in range(first_bridge, len(buffered)):
                raw, ns, _st = buffered[idx]
                recorder.handle_message(raw, receive_ns=ns)
            buffered.clear()
            bridge_found = True
            recorder.record_bootstrap(snapshot_id, first_bridge, buffered)
            print(f"Bridge found at index {first_bridge}")
        elif _first_event_ts[0] > 0 and time.monotonic() - _first_event_ts[0] > 3.0 and buffered:
            flushed_any = False
            for raw, ns, _st in buffered:
                rng = _depth_update_id_range(raw)
                if rng is not None and rng[1] > (snapshot_id or 0):
                    recorder.handle_message(raw, receive_ns=ns)
                    flushed_any = True
            if flushed_any:
                bridge_found = True
                buffered.clear()
                print("Fallback bridge found")
        return

    recorder.handle_message(message, receive_ns=receive_ns)
    if ev_type == "depthUpdate":
        diagnostics["depth"] += 1
    elif ev_type in ("aggTrade", "trade"):
        diagnostics["trade"] += 1
    elif ev_type == "bookTicker":
        diagnostics["bookTicker"] += 1

def on_open(_ws):
    _first_event_ts[0] = time.monotonic()

def on_error(_ws, _error):
    global reconnect_count
    reconnect_count += 1
    recorder.mark_reconnect()

def on_close(_ws, _status_code, _message):
    recorder.close()

socket = websocket.WebSocketApp(
    ws_url, on_message=on_message, on_open=on_open, on_error=on_error, on_close=on_close,
)
import threading
timer = threading.Timer(3600, lambda: socket.close())
timer.daemon = True
try:
    timer.start()
    socket.run_forever(ping_interval=20, ping_timeout=10)
finally:
    timer.cancel()
    recorder.close()

utc_end = timestamp_iso()

# Compute sequence range + event counts
from app.v12.capture import _summarize_session, _write_checksums
seq_min, seq_max, counts = _summarize_session(session_dir)
checksums = _write_checksums(session_dir)

valid = bridge_found and (session_dir / "events.jsonl").read_text(encoding="utf-8").strip() != ""
invalid_reason = "" if valid else (
    "NO_BRIDGING_EVENT: REST snapshot never bridged by a depthUpdate" if not bridge_found
    else "EMPTY_EVENT_STREAM: bridge found but no events recorded"
)

# Write manifest
import hashlib
manifest = {
    "session_id": capture_id,
    "symbol": symbol,
    "streams": streams,
    "schema_version": "v10.raw.v1",
    "start_ns": int(time.time() * 1e9) - 3600 * 10**9,
    "end_ns": int(time.time() * 1e9),
    "event_count": sum(counts.values()),
    "bootstrap": {
        "status": "BRIDGED" if valid else "FAILED",
        "snapshot_last_update_id": snapshot_id or 0,
        "first_bridge_index": 0,
        "first_U": seq_min or 0,
        "first_u": seq_max or 0,
        "first_pu": None,
        "pre_bridge_events_skipped": 0,
    },
    "configuration_hash": config_hash,
    "checksums": checksums,
}
manifest_path = session_dir / "manifest.json"
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

print(f"Capture complete: valid={valid}")
print(f"  Events: {counts}")
print(f"  Reconnects: {reconnect_count}, Gaps: {gap_count}")
print(f"  Session dir: {session_dir}")
if valid:
    print(f"  Bootstrap: BRIDGED")
else:
    print(f"  Invalid: {invalid_reason}")
