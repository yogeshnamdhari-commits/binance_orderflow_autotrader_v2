"""Research-only V10 market-data capture primitives.

This module deliberately does not place orders and does not depend on the
production trading path. It preserves raw Binance WebSocket payloads while
adding only local observability metadata needed for later replay/audit.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class SequenceStatus:
    state: str
    previous_u: int | None
    current_U: int | None
    current_u: int | None
    reason: str | None = None


@dataclass(frozen=True)
class NormalizedEvent:
    stream: str | None
    event_type: str | None
    event_time_ms: int | None
    receive_time_ns: int
    raw_json: str
    payload: dict[str, Any]


def normalize_ws_event(raw_json: str, receive_ns: int | None = None) -> NormalizedEvent:
    """Parse only envelope metadata while retaining the exact raw JSON text."""
    if not isinstance(raw_json, str):
        raise TypeError("raw_json must be a string")
    payload = json.loads(raw_json)
    if not isinstance(payload, dict):
        raise ValueError("WebSocket payload must be a JSON object")
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        raise ValueError("WebSocket event data must be a JSON object")
    event_time = data.get("E")
    return NormalizedEvent(
        stream=payload.get("stream"),
        event_type=data.get("e"),
        event_time_ms=int(event_time) if event_time is not None else None,
        receive_time_ns=time.time_ns() if receive_ns is None else int(receive_ns),
        raw_json=raw_json,
        payload=payload,
    )


class DepthSequenceValidator:
    """Validate Binance diff-depth continuity without modifying input events."""

    def __init__(self) -> None:
        self.previous_u: int | None = None

    def observe(self, event: dict[str, Any]) -> SequenceStatus:
        try:
            first_update = int(event["U"])
            final_update = int(event["u"])
            previous_update = event.get("pu")
            previous_update = int(previous_update) if previous_update is not None else None
        except (KeyError, TypeError, ValueError):
            return SequenceStatus("MALFORMED", self.previous_u, None, None, "MISSING_OR_INVALID_SEQUENCE_FIELDS")

        if first_update > final_update:
            return SequenceStatus("MALFORMED", self.previous_u, first_update, final_update, "U_GT_U")

        if self.previous_u is None:
            self.previous_u = final_update
            return SequenceStatus("FIRST", None, first_update, final_update)

        previous = self.previous_u
        if previous_update is not None and previous_update != previous:
            self.previous_u = final_update
            return SequenceStatus("GAP", previous, first_update, final_update, "PU_MISMATCH")

        if first_update > previous + 1 or final_update <= previous:
            self.previous_u = final_update
            return SequenceStatus("GAP", previous, first_update, final_update, "UPDATE_ID_GAP")

        self.previous_u = final_update
        return SequenceStatus("CONTIGUOUS", previous, first_update, final_update)


class SessionRecorder:
    """Append-only raw-event recorder for one research capture session."""

    SCHEMA_VERSION = "v10.raw.v1"

    def __init__(self, output_dir: str | Path, symbol: str, streams: Iterable[str], session_id: str | None = None) -> None:
        self.output_dir = Path(output_dir)
        self.symbol = symbol.upper()
        self.streams = list(streams)
        self.session_id = session_id or uuid.uuid4().hex
        self.session_dir: Path | None = None
        self._events = None
        self._manifest: dict[str, Any] | None = None

    def start(self, start_ns: int | None = None) -> Path:
        if self._events is not None:
            raise RuntimeError("session already started")
        start_ns = time.time_ns() if start_ns is None else int(start_ns)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session_dir = self.output_dir / self.session_id
        self.session_dir.mkdir(parents=False, exist_ok=False)
        self._events = (self.session_dir / "events.jsonl").open("a", encoding="utf-8")
        self._manifest = {
            "schema_version": self.SCHEMA_VERSION,
            "symbol": self.symbol,
            "streams": self.streams,
            "session_id": self.session_id,
            "start_ns": start_ns,
            "end_ns": None,
            "event_count": 0,
        }
        self._write_manifest()
        return self.session_dir

    def record_raw(self, raw_json: str, receive_ns: int | None = None) -> None:
        if self._events is None or self._manifest is None:
            raise RuntimeError("session is not started")
        normalized = normalize_ws_event(raw_json, receive_ns)
        row = {
            "receive_ns": normalized.receive_time_ns,
            "stream": normalized.stream,
            "event_type": normalized.event_type,
            "event_time_ms": normalized.event_time_ms,
            "raw_json": normalized.raw_json,
        }
        self._events.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        self._events.flush()
        self._manifest["event_count"] += 1

    def close(self, end_ns: int | None = None) -> None:
        if self._events is None or self._manifest is None:
            return
        self._manifest["end_ns"] = time.time_ns() if end_ns is None else int(end_ns)
        self._write_manifest()
        self._events.close()
        self._events = None

    def _write_manifest(self) -> None:
        assert self.session_dir is not None
        assert self._manifest is not None
        (self.session_dir / "manifest.json").write_text(
            json.dumps(self._manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
