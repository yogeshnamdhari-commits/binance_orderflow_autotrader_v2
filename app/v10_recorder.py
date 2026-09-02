"""V10 Binance public market-data capture adapter.

No trading or account endpoints are used here. The adapter exists solely to
capture public USDⓈ-M WebSocket market data for deterministic research replay.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit, urlunsplit

from .v10_market_data import DepthSequenceValidator, SessionRecorder, normalize_ws_event


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
        parts = urlsplit(self.ws_url)
        combined = "/".join(self.streams)
        return urlunsplit((parts.scheme, parts.netloc, f"{parts.path}/{combined}", "", parts.fragment))

    def start(self, start_ns: int | None = None) -> Path:
        return self.session.start(start_ns=start_ns)

    def handle_message(self, raw_json: str, receive_ns: int | None = None) -> None:
        receive_ns = self.clock_ns() if receive_ns is None and self.clock_ns is not None else receive_ns
        self._diagnostics["total_events"] += 1
        try:
            event = normalize_ws_event(raw_json, receive_ns=receive_ns)
        except Exception:
            self._diagnostics["parse_errors"] += 1
            self.session.record_raw(raw_json, receive_ns=receive_ns)
            return

        if event.event_type == "depthUpdate":
            self._diagnostics["depth_events"] += 1
            self.session.record_raw(raw_json, receive_ns=receive_ns, stream_override="btcusdt@depth@100ms")
            status = self.depth_validator.observe(event.payload.get("data", event.payload))
            if status.state == "GAP":
                self._diagnostics["gaps"] += 1
        elif event.event_type in ("trade", "aggTrade"):
            self._diagnostics["trade_events"] += 1
            self.session.record_raw(raw_json, receive_ns=receive_ns, stream_override="btcusdt@trade")
        elif event.event_type == "bookTicker":
            self._diagnostics["book_ticker_events"] += 1
            self.session.record_raw(raw_json, receive_ns=receive_ns, stream_override="btcusdt@bookTicker")
        else:
            self.session.record_raw(raw_json, receive_ns=receive_ns)

    def mark_reconnect(self) -> None:
        self._diagnostics["reconnect_boundaries"] += 1
        self.depth_validator = DepthSequenceValidator()

    def diagnostics(self) -> dict[str, int]:
        return dict(self._diagnostics)

    def close(self, end_ns: int | None = None) -> None:
        self.session.close(end_ns=end_ns)
