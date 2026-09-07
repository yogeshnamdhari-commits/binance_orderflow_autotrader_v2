"""Deterministic audit for V10 raw market-data sessions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .v10_market_data import DepthSequenceValidator, normalize_ws_event


def audit_session(session_dir: str | Path) -> dict[str, Any]:
    session_dir = Path(session_dir)
    manifest_path = session_dir / "manifest.json"
    events_path = session_dir / "events.jsonl"
    snapshot_path = session_dir / "snapshot.json"

    result: dict[str, Any] = {
        "manifest_present": manifest_path.is_file(),
        "events_present": events_path.is_file(),
        "snapshot_present": snapshot_path.is_file(),
        "snapshot_bridge_pass": False,
        "snapshot_bridge_gap": 0,
        "event_count": 0,
        "malformed_rows": 0,
        "raw_event_parse_errors": 0,
        "missing_metadata_count": 0,
        "receive_time_regressions": 0,
        "event_time_regressions": 0,
        "duplicate_raw_count": 0,
        "depth_event_count": 0,
        "depth_gap_count": 0,
        "depth_malformed_count": 0,
        "parse_integrity_pass": False,
        "timestamp_monotonicity_pass": False,
        "duplicate_raw_pass": False,
        "required_metadata_pass": False,
        "depth_continuity_pass": False,
        "overall_pass": False,
    }

    if not manifest_path.is_file() or not events_path.is_file():
        return result

    snapshot_last_update_id: int | None = None
    if snapshot_path.is_file():
        try:
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            snapshot_last_update_id = int(snapshot.get("lastUpdateId", -1))
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            snapshot_last_update_id = None

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_ok = (
            manifest.get("schema_version") == "v10.raw.v1"
            and isinstance(manifest.get("symbol"), str)
            and bool(manifest.get("symbol"))
        )
    except (OSError, json.JSONDecodeError):
        manifest = {}
        manifest_ok = False

    validators: dict[str, DepthSequenceValidator] = {}
    last_receive: dict[str, int] = {}
    last_event_time: dict[str, int] = {}
    raw_hashes: set[str] = set()
    duplicate_count = 0
    bridge_checked = False

    try:
        lines = events_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return result

    for line in lines:
        if not line.strip():
            continue
        result["event_count"] += 1
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            result["malformed_rows"] += 1
            continue

        if not isinstance(row, dict):
            result["malformed_rows"] += 1
            continue

        required = ("stream", "event_type", "receive_ns", "raw_json")
        if any(key not in row or row[key] in (None, "") for key in required):
            result["missing_metadata_count"] += 1
            continue

        raw_json = row["raw_json"]
        if not isinstance(raw_json, str):
            result["missing_metadata_count"] += 1
            continue

        digest = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()
        if digest in raw_hashes:
            duplicate_count += 1
        raw_hashes.add(digest)

        stream = str(row["stream"])
        receive_ns = int(row["receive_ns"])
        previous_receive = last_receive.get(stream)
        if previous_receive is not None and receive_ns < previous_receive:
            result["receive_time_regressions"] += 1
        last_receive[stream] = receive_ns

        if row.get("event_time_ms") is not None:
            event_time = int(row["event_time_ms"])
            previous_event_time = last_event_time.get(stream)
            if previous_event_time is not None and event_time < previous_event_time:
                result["event_time_regressions"] += 1
            last_event_time[stream] = event_time

        try:
            event = normalize_ws_event(raw_json, receive_ns=receive_ns)
        except Exception:
            result["raw_event_parse_errors"] += 1
            continue

        if event.event_type != "depthUpdate":
            continue

        result["depth_event_count"] += 1
        validator = validators.setdefault(stream, DepthSequenceValidator())
        status = validator.observe(event.payload.get("data", event.payload))
        if status.state == "GAP":
            result["depth_gap_count"] += 1
        elif status.state == "MALFORMED":
            result["depth_malformed_count"] += 1

        if snapshot_last_update_id is not None and not bridge_checked:
            data = event.payload.get("data", event.payload)
            try:
                U = int(data["U"])
                u = int(data["u"])
                if U <= snapshot_last_update_id + 1 <= u:
                    result["snapshot_bridge_pass"] = True
                elif U > snapshot_last_update_id + 1:
                    result["snapshot_bridge_pass"] = False
                    result["snapshot_bridge_gap"] = max(
                        result["snapshot_bridge_gap"], U - snapshot_last_update_id - 1
                    )
            except (KeyError, TypeError, ValueError):
                pass
            bridge_checked = True

    if snapshot_last_update_id is not None and not bridge_checked:
        result["snapshot_bridge_pass"] = False

    result["duplicate_raw_count"] = duplicate_count
    result["parse_integrity_pass"] = result["malformed_rows"] == 0 and result["raw_event_parse_errors"] == 0
    result["timestamp_monotonicity_pass"] = (
        result["receive_time_regressions"] == 0 and result["event_time_regressions"] == 0
    )
    result["duplicate_raw_pass"] = result["duplicate_raw_count"] == 0
    result["required_metadata_pass"] = manifest_ok and result["missing_metadata_count"] == 0
    result["depth_continuity_pass"] = (
        result["depth_gap_count"] == 0 and result["depth_malformed_count"] == 0
    )
    result["overall_pass"] = all(
        result[key]
        for key in (
            "parse_integrity_pass",
            "timestamp_monotonicity_pass",
            "duplicate_raw_pass",
            "required_metadata_pass",
            "depth_continuity_pass",
            "snapshot_bridge_pass",
        )
    )
    return result
