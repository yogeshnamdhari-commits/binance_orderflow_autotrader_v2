"""V10 Binance public market-data capture adapter.

No trading or account endpoints are used here. The adapter exists solely to
capture public USDⓈ-M market data with strict depth provenance.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .v10_market_data import (
    DepthSequenceValidator,
    SessionRecorder,
    normalize_ws_event,
)


def _depth_update_id_range(raw_json: str) -> tuple[int, int] | None:
    try:
        payload = json.loads(raw_json)
        data = payload.get("data", payload)
        return int(data["U"]), int(data["u"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


class V10Recorder:
    def __init__(
        self,
        symbol: str,
        output_dir: str | Path,
        ws_url: str,
        streams: list[str],
        clock_ns: Callable[[], int] | None = None,
    ) -> None:
        self.symbol = symbol.upper()
        self.output_dir = Path(output_dir)
        self.ws_url = ws_url
        self.streams = list(streams)
        self.clock_ns = clock_ns
        self.session = SessionRecorder(self.output_dir, self.symbol, self.streams)
        self.depth_validator = DepthSequenceValidator()
        self._diagnostics = {
            "total_events": 0,
            "depth_events": 0,
            "trade_events": 0,
            "book_ticker_events": 0,
            "parse_errors": 0,
            "gaps": 0,
            "reconnect_boundaries": 0,
        }

    def build_stream_url(self) -> str:
        return f"{self.ws_url}/stream?streams={'/'.join(self.streams)}"

    def start(self, start_ns: int | None = None) -> Path:
        return self.session.start(start_ns=start_ns)

    def handle_message(self, raw_json: str, receive_ns: int | None = None) -> None:
        if receive_ns is None and self.clock_ns is not None:
            receive_ns = self.clock_ns()
        self.session.record_raw(raw_json, receive_ns=receive_ns)
        self._diagnostics["total_events"] += 1
        try:
            event = normalize_ws_event(raw_json, receive_ns=receive_ns)
        except Exception:
            self._diagnostics["parse_errors"] += 1
            return

        if event.event_type == "depthUpdate":
            self._diagnostics["depth_events"] += 1
            status = self.depth_validator.observe(event.payload.get("data", event.payload))
            if status.state in {"GAP", "MALFORMED"}:
                self._diagnostics["gaps"] += 1
        elif event.event_type in ("trade", "aggTrade"):
            self._diagnostics["trade_events"] += 1
        elif event.event_type == "bookTicker":
            self._diagnostics["book_ticker_events"] += 1

    def mark_reconnect(self) -> None:
        self._diagnostics["reconnect_boundaries"] += 1
        self.depth_validator = DepthSequenceValidator()

    def diagnostics(self) -> dict[str, int]:
        return dict(self._diagnostics)

    def record_bootstrap(
        self,
        snapshot_id: int,
        bridge_index: int,
        buffered: list[tuple[str, int, str | None]],
        snapshot_source: str = "REST",
    ) -> None:
        if bridge_index < 0 or bridge_index >= len(buffered):
            raise RuntimeError(f"invalid bridge index: {bridge_index}")

        first_raw = buffered[bridge_index][0]
        range_result = _depth_update_id_range(first_raw)
        if range_result is None:
            raise RuntimeError("bridge event is not a valid depthUpdate")
        first_U, first_u = range_result
        expected = int(snapshot_id) + 1
        if not (first_U <= expected <= first_u):
            raise RuntimeError(
                "bridge event does not bracket snapshot_last_update_id+1: "
                f"expected={expected}, U={first_U}, u={first_u}"
            )

        first_pu = None
        try:
            payload = json.loads(first_raw)
            data = payload.get("data", payload)
            if data.get("pu") is not None:
                first_pu = int(data["pu"])
        except Exception:
            pass

        # Pre-bridge events are discarded because they cannot be causally
        # joined to the snapshot. Sequence validation restarts at the bridge.
        self.session.reset_event_log_for_bridge()
        self.depth_validator = DepthSequenceValidator()
        self.depth_validator.bootstrap(int(snapshot_id))

        for key in (
            "total_events",
            "depth_events",
            "trade_events",
            "book_ticker_events",
            "parse_errors",
            "gaps",
        ):
            self._diagnostics[key] = 0

        self.session._manifest["bootstrap"] = {
            "status": "BRIDGED",
            "snapshot_last_update_id": int(snapshot_id),
            "snapshot_source": snapshot_source,
            "first_bridge_index": bridge_index,
            "first_U": first_U,
            "first_u": first_u,
            "first_pu": first_pu,
            "pre_bridge_events_skipped": bridge_index,
            "pre_bridge_event_rows_discarded": bridge_index,
            "bridge_rule": "U <= snapshot_last_update_id + 1 <= u",
            "post_bridge_rule": "pu == previous_u",
        }
        self.session._write_manifest()

    def record_bootstrap_failure(self, snapshot_id: int, reason: str, detail: str) -> None:
        self.session._manifest["bootstrap"] = {
            "status": "FAILED",
            "snapshot_last_update_id": snapshot_id,
            "reason": reason,
            "detail": detail,
        }
        self.session._write_manifest()

    def close(self, end_ns: int | None = None) -> None:
        self.session.close(end_ns=end_ns)
