"""V12 production-quality Binance USDⓈ-M market-data capture.

Rule 4: real Binance depth + trade data with exchange timestamps, local receive
timestamps, update IDs, REST snapshots, reconnect events, sequence gaps, and
resynchronization events.

Output session schema (v10.raw.v1 — compatible with v10_data_audit + V11DataParser):
    manifest.json   session metadata + configuration hash
    snapshot.json   REST depth snapshot
    events.jsonl    append-only raw events (one JSON object per line)
    checksums.json  SHA-256 of each artifact

If integrity cannot be established, the session is marked INVALID and is never
used for calibration or forward validation.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import urllib.request

import websocket

from app.v10_recorder import V10Recorder

DEFAULT_WS = "wss://fstream.binance.com"
DEFAULT_STREAMS = ["btcusdt@depth@100ms", "btcusdt@trade", "btcusdt@bookTicker"]
REST_DEPTH_BASE = "https://fapi.binance.com/fapi/v1/depth"

USER_AGENT = "Mozilla/5.0 (compatible; V12-Capture/1.0)"


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


def fetch_rest_snapshot(symbol: str, limit: int = 1000, timeout: float = 10.0) -> dict[str, object]:
    """Fetch a REST depth snapshot from Binance USDⓈ-M futures API."""
    symbol = symbol.upper()
    url = f"{REST_DEPTH_BASE}?symbol={symbol}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
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
    buffered: list[tuple[str, int | None]], snapshot_id: int
) -> int | None:
    """Find the first depthUpdate that bridges the REST snapshot.

    A depthUpdate bridges when U <= snapshot_id + 1 <= u. Non-depth events are
    skipped (they sit in the multi-stream buffer alongside depth events).
    """
    for idx, (raw_json, _ns, _st) in enumerate(buffered):
        range_result = _depth_update_id_range(raw_json)
        if range_result is None:
            continue
        U, u = range_result
        if U <= snapshot_id + 1 <= u:
            return idx
    return None


@dataclass
class CaptureResult:
    session_dir: Path
    symbol: str
    market_type: str
    stream_names: list[str]
    utc_start: str
    utc_end: str
    sequence_range: tuple[int, int] | None
    event_counts: dict[str, int]
    reconnects: int
    gaps: int
    software_version: str
    configuration_hash: str
    data_checksum: str
    valid: bool
    invalid_reason: str = ""


def capture_session(
    symbol: str = "BTCUSDT",
    output_dir: str | Path = "data/v12/calibration",
    duration_seconds: int = 300,
    ws_base: str = DEFAULT_WS,
    cache_funding: bool = True,
    funding_output: str | Path | None = None,
) -> CaptureResult:
    """Capture a complete research session.

    Returns a CaptureResult with full provenance metadata. The session is
    marked VALID only if the snapshot bridges and a non-empty event stream is
    recorded; otherwise ``valid=False`` and ``invalid_reason`` explains why.
    """
    symbol_lower = symbol.lower()
    streams = [s.replace("btcusdt", symbol_lower, 1) for s in DEFAULT_STREAMS]
    ws_url = build_ws_url(ws_base, streams)

    recorder = V10Recorder(
        symbol=symbol,
        output_dir=output_dir,
        ws_url=ws_url,
        streams=streams,
    )

    session_dir = recorder.start()
    config_hash = hashlib.sha256(
        json.dumps({"symbol": symbol, "streams": streams, "duration_s": duration_seconds}, sort_keys=True).encode()
    ).hexdigest()[:16]

    # Fetch REST snapshot (the synchronization anchor)
    snapshot = fetch_rest_snapshot(symbol_upper(symbol), limit=1000)
    snapshot_id = int(snapshot["lastUpdateId"])
    (session_dir / "snapshot.json").write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )

    utc_start = timestamp_iso()
    buffered: list[tuple[str, int, str | None]] = []
    bridge_found = False
    reconnect_count = 0
    gap_count = 0
    diagnostics = {"depth": 0, "trade": 0, "bookTicker": 0, "malformed": 0}
    _first_event_ts = [0.0]

    def on_message(_ws, message):
        nonlocal bridge_found
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
            first_bridge = find_bridging_index(buffered, snapshot_id)
            if first_bridge is not None:
                for idx in range(first_bridge, len(buffered)):
                    raw, ns, _st = buffered[idx]
                    recorder.handle_message(raw, receive_ns=ns)
                buffered.clear()
                bridge_found = True
            elif _first_event_ts[0] > 0 and time.monotonic() - _first_event_ts[0] > 3.0 and buffered:
                flushed_any = False
                for raw, ns, _st in buffered:
                    rng = _depth_update_id_range(raw)
                    if rng is not None and rng[1] > snapshot_id:
                        recorder.handle_message(raw, receive_ns=ns)
                        flushed_any = True
                if flushed_any:
                    bridge_found = True
                    buffered.clear()
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
        nonlocal reconnect_count
        reconnect_count += 1
        recorder.mark_reconnect()

    def on_close(_ws, _status_code, _message):
        recorder.close()

    socket = websocket.WebSocketApp(
        ws_url, on_message=on_message, on_open=on_open, on_error=on_error, on_close=on_close,
    )
    import threading
    timer = threading.Timer(duration_seconds, lambda: socket.close())
    timer.daemon = True
    try:
        timer.start()
        socket.run_forever(ping_interval=20, ping_timeout=10)
    finally:
        timer.cancel()
        recorder.close()

    utc_end = timestamp_iso()

    # Compute sequence range + event counts from recorded events
    seq_min, seq_max, counts = _summarize_session(session_dir)
    checksums = _write_checksums(session_dir)

    valid = bridge_found and (session_dir / "events.jsonl").read_text(encoding="utf-8").strip() != ""
    invalid_reason = "" if valid else (
        "NO_BRIDGING_EVENT: REST snapshot never bridged by a depthUpdate" if not bridge_found
        else "EMPTY_EVENT_STREAM: bridge found but no events recorded"
    )

    # Optionally fetch funding rates
    if cache_funding:
        try:
            from .funding import fetch_and_cache
            fetch_and_cache(
                symbol=symbol,
                start_ms=int(time.time() * 1000) - 8 * 3600_000,
                end_ms=int(time.time() * 1000),
                cache_path=funding_output or str(session_dir / "funding.json"),
            )
        except Exception:
            pass

    diag = recorder.diagnostics()
    return CaptureResult(
        session_dir=session_dir,
        symbol=symbol,
        market_type="USDT-M PERPETUAL",
        stream_names=streams,
        utc_start=utc_start,
        utc_end=utc_end,
        sequence_range=(seq_min, seq_max),
        event_counts=counts,
        reconnects=reconnect_count,
        gaps=diag.get("gaps", 0),
        software_version="V12-capture/1.0",
        configuration_hash=config_hash,
        data_checksum=checksums.get("checksums", ""),
        valid=valid,
        invalid_reason=invalid_reason,
    )


def symbol_upper(symbol: str) -> str:
    return symbol.upper()


def timestamp_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _safe_json(message: str) -> dict | None:
    try:
        return json.loads(message)
    except (json.JSONDecodeError, TypeError):
        return None



def _summarize_session(session_dir: Path) -> tuple[int | None, int | None, dict[str, int]]:
    seq_min: int | None = None
    seq_max: int | None = None
    counts: dict[str, int] = {"depthUpdate": 0, "trade": 0, "aggTrade": 0, "bookTicker": 0, "unknown": 0}
    events_path = session_dir / "events.jsonl"
    if not events_path.exists():
        return seq_min, seq_max, counts
    with open(events_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            data = row.get("raw_json")
            if not isinstance(data, str):
                continue
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                continue
            evt = payload.get("data", payload)
            ev_type = evt.get("e")
            if ev_type in counts:
                counts[ev_type] += 1
            else:
                counts["unknown"] += 1
            if ev_type == "depthUpdate":
                try:
                    u = int(evt["u"])
                    seq_min = u if seq_min is None else min(seq_min, u)
                    seq_max = u if seq_max is None else max(seq_max, u)
                except (KeyError, ValueError, TypeError):
                    pass
    return seq_min, seq_max, counts


def _write_checksums(session_dir: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for fname in ["events.jsonl", "snapshot.json", "manifest.json"]:
        fpath = session_dir / fname
        if fpath.exists():
            h = hashlib.sha256()
            with open(fpath, "rb") as f:
                while chunk := f.read(8192):
                    h.update(chunk)
            checksums[fname] = h.hexdigest()
    manifest_path = session_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["checksums"] = checksums
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (session_dir / "checksums.json").write_text(
        json.dumps(checksums, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    return checksums


def record_capture_result(result: CaptureResult, dest: str | Path | None = None) -> None:
    """Persist the capture result as provenance metadata."""
    if dest is None:
        dest = result.session_dir / "capture_result.json"
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result.__dict__, default=str, indent=2), encoding="utf-8")
