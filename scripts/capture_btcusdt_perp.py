#!/usr/bin/env python3
"""Capture authentic BTCUSDT USDⓈ-M perpetual market data.

Research infrastructure only. This script never places orders.

Streams:
  - BTCUSDT depth@100ms via the current USD-M /public market-data path
  - BTCUSDT aggTrade via the current USD-M /market path
  - BTCUSDT markPrice@1s via the current USD-M /market path

The initial order-book snapshot is requested through Binance Futures' public
WebSocket API (method=depth). The depth stream starts first and is buffered until
the snapshot lastUpdateId can be bridged. Updates older than the snapshot are
discarded. The first spanning update starts the local book sequence; every later
update must satisfy pu == previous_u. Any gap or reconnect invalidates the
capture.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import threading
import time
import uuid

import websocket


SYMBOL = "BTCUSDT"
WS_PUBLIC_RAW = "wss://fstream.binance.com/public/ws"
WS_MARKET_COMBINED = "wss://fstream.binance.com/market/stream"
WS_API = "wss://ws-fapi.binance.com/ws-fapi/v1"


class Capture:
    def __init__(self, out: Path, duration_s: int) -> None:
        self.out = out
        self.duration_s = duration_s
        self.out.mkdir(parents=True, exist_ok=False)

        self.events_path = self.out / "events.jsonl"
        self.snapshot_path = self.out / "snapshot.json"
        self.events_file = self.events_path.open("w", encoding="utf-8", buffering=1)

        self.lock = threading.Lock()
        self.started_ns = time.time_ns()
        self.stopped = threading.Event()

        self.buffer: list[dict] = []
        self.snapshot_last_id: int | None = None
        self.bridged = False
        self.previous_u: int | None = None
        self.bootstrap_dropped = 0

        self.event_count = 0
        self.depth_count = 0
        self.trade_count = 0
        self.mark_count = 0
        self.sequence_gaps = 0
        self.reconnects = 0
        self.errors: list[str] = []
        self.websocket_threads: list[threading.Thread] = []

    def write_row(self, event_type: str, raw: str, **extra) -> None:
        row = {
            "event_type": event_type,
            "received_ns": time.time_ns(),
            "raw_json": raw,
            **extra,
        }
        with self.lock:
            self.events_file.write(json.dumps(row, separators=(",", ":")) + "\n")
            self.event_count += 1

    def _snapshot_ws(self) -> dict:
        request_id = uuid.uuid4().hex
        ws = websocket.create_connection(WS_API, timeout=10)
        try:
            ws.send(
                json.dumps(
                    {
                        "id": request_id,
                        "method": "depth",
                        "params": {
                            "symbol": SYMBOL,
                            "limit": 1000,
                            "returnRateLimits": False,
                        },
                    },
                    separators=(",", ":"),
                )
            )
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                raw = ws.recv()
                if not raw:
                    continue
                payload = json.loads(raw)
                if str(payload.get("id")) != request_id:
                    continue
                if int(payload.get("status", 0)) != 200:
                    raise RuntimeError(
                        f"Binance Futures WebSocket depth request failed: {payload}"
                    )
                result = payload.get("result")
                if not isinstance(result, dict) or "lastUpdateId" not in result:
                    raise RuntimeError(
                        "invalid BTCUSDT Futures WebSocket depth snapshot"
                    )
                return result
            raise TimeoutError(
                "timed out waiting for BTCUSDT Futures WebSocket depth snapshot"
            )
        finally:
            ws.close()

    def fetch_snapshot(self) -> None:
        payload = self._snapshot_ws()
        self.snapshot_last_id = int(payload["lastUpdateId"])
        self.snapshot_path.write_text(
            json.dumps(
                {
                    "T": int(payload.get("T", time.time() * 1000)),
                    "E": int(payload.get("E", 0)),
                    "lastUpdateId": self.snapshot_last_id,
                    "bids": payload["bids"],
                    "asks": payload["asks"],
                    "source": "binance_usdm_websocket_api.depth",
                    "endpoint": WS_API,
                },
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )

    def _unwrap(self, raw: str) -> tuple[dict, str]:
        envelope = json.loads(raw)
        data = envelope.get("data", envelope)
        return data, json.dumps(envelope, separators=(",", ":"))

    @staticmethod
    def _bridges(snapshot_id: int, data: dict) -> bool:
        U = int(data["U"])
        u = int(data["u"])
        pu = int(data.get("pu", 0))
        return (U <= snapshot_id <= u) or (pu == snapshot_id)

    def _write_and_advance_depth(self, raw: str, data: dict) -> None:
        self.previous_u = int(data["u"])
        self.depth_count += 1
        self.write_row("depthUpdate", raw)

    def _finish_bootstrap(self) -> None:
        """Bridge the buffered feed to the snapshot, then replay only later updates."""
        assert self.snapshot_last_id is not None

        pending = list(self.buffer)
        self.buffer.clear()

        bridge_index = -1
        for i, item in enumerate(pending):
            if self._bridges(self.snapshot_last_id, item["data"]):
                bridge_index = i
                break

        if bridge_index < 0:
            # Caller will append the current event and retry on the next message.
            self.buffer.extend(pending)
            return

        # Everything before the bridge update is older than the snapshot state.
        self.bootstrap_dropped += bridge_index
        bridge = pending[bridge_index]
        self.bridged = True
        self._write_and_advance_depth(bridge["raw"], bridge["data"])

        for item in pending[bridge_index + 1 :]:
            self._process_live_depth(item["raw"], item["data"])

    def _process_live_depth(self, raw: str, data: dict) -> None:
        pu = int(data.get("pu", 0))
        u = int(data["u"])

        if self.previous_u is None:
            raise RuntimeError("depth sequence has no previous update id")
        if pu != self.previous_u:
            self.sequence_gaps += 1
            raise RuntimeError(
                f"BTCUSDT Futures L2 sequence gap: expected pu={self.previous_u}, got pu={pu}"
            )

        self.previous_u = u
        self.depth_count += 1
        self.write_row("depthUpdate", raw)

    def process_depth(self, raw: str, data: dict) -> None:
        if not self.bridged:
            self.buffer.append({"raw": raw, "data": data})
            if self.snapshot_last_id is not None:
                self._finish_bootstrap()
            return

        self._process_live_depth(raw, data)

    def on_depth_message(self, _ws, raw: str) -> None:
        try:
            data, envelope = self._unwrap(raw)
            if data.get("e") == "depthUpdate":
                self.process_depth(envelope, data)
        except Exception as exc:
            if not self.stopped.is_set():
                self.errors.append(str(exc))
                self.stopped.set()

    def on_market_message(self, _ws, raw: str) -> None:
        try:
            data, envelope = self._unwrap(raw)
            event = data.get("e")
            if event == "aggTrade":
                self.trade_count += 1
                self.write_row("aggTrade", envelope)
            elif event == "markPriceUpdate":
                self.mark_count += 1
                self.write_row("markPriceUpdate", envelope)
        except Exception as exc:
            if not self.stopped.is_set():
                self.errors.append(str(exc))
                self.stopped.set()

    def on_error(self, _ws, error) -> None:
        if not self.stopped.is_set():
            self.errors.append(f"WebSocket error: {error}")
            self.stopped.set()

    def on_close(self, _ws, _code, _msg) -> None:
        if not self.stopped.is_set():
            self.reconnects += 1
            self.errors.append("WebSocket closed before capture completion")
            self.stopped.set()

    def _run_socket(self, ws: websocket.WebSocketApp) -> None:
        ws.run_forever(ping_interval=20, ping_timeout=10)

    def run(self) -> None:
        depth_url = f"{WS_PUBLIC_RAW}/{SYMBOL.lower()}@depth@100ms"
        market_url = (
            f"{WS_MARKET_COMBINED}?streams="
            f"{SYMBOL.lower()}@aggTrade/{SYMBOL.lower()}@markPrice@1s"
        )

        depth_ws = websocket.WebSocketApp(
            depth_url,
            on_message=self.on_depth_message,
            on_error=self.on_error,
            on_close=self.on_close,
        )
        market_ws = websocket.WebSocketApp(
            market_url,
            on_message=self.on_market_message,
            on_error=self.on_error,
            on_close=self.on_close,
        )

        depth_thread = threading.Thread(
            target=lambda: self._run_socket(depth_ws),
            daemon=True,
            name="btc-depth",
        )
        market_thread = threading.Thread(
            target=lambda: self._run_socket(market_ws),
            daemon=True,
            name="btc-market",
        )
        self.websocket_threads = [depth_thread, market_thread]
        depth_thread.start()
        market_thread.start()

        time.sleep(0.5)
        self.fetch_snapshot()

        deadline = time.monotonic() + self.duration_s
        while time.monotonic() < deadline and not self.stopped.is_set():
            time.sleep(0.25)

        self.stopped.set()
        depth_ws.close()
        market_ws.close()
        for thread in self.websocket_threads:
            thread.join(timeout=5)

        try:
            if self.errors:
                raise RuntimeError("; ".join(self.errors))
            if not self.bridged:
                raise RuntimeError("capture ended without a valid snapshot/depth bridge")
            if self.sequence_gaps:
                raise RuntimeError(f"capture ended with {self.sequence_gaps} sequence gaps")
            if self.reconnects:
                raise RuntimeError(f"capture ended with {self.reconnects} reconnects")
            if not self.trade_count or not self.mark_count:
                raise RuntimeError("capture lacks required trade/mark-price observations")

            manifest = {
                "schema_version": "AFH01-BTCUSDT-USD-M-PERP-v1",
                "session_id": self.out.name,
                "symbol": SYMBOL,
                "market": "USD-M",
                "instrument": "PERPETUAL",
                "exchange": "BINANCE",
                "streams": [
                    "btcusdt@depth@100ms",
                    "btcusdt@aggTrade",
                    "btcusdt@markPrice@1s",
                ],
                "stream_endpoints": {
                    "depth": depth_url,
                    "market": market_url,
                    "snapshot": WS_API,
                },
                "start_ns": self.started_ns,
                "end_ns": time.time_ns(),
                "event_count": self.event_count,
                "depth_events": self.depth_count,
                "trade_events": self.trade_count,
                "mark_price_events": self.mark_count,
                "sequence_gaps": self.sequence_gaps,
                "reconnects": self.reconnects,
                "bootstrap": {
                    "status": "BRIDGED",
                    "snapshot_last_update_id": self.snapshot_last_id,
                    "snapshot_source": "websocket_api.depth",
                    "dropped_pre_snapshot_events": self.bootstrap_dropped,
                },
                "certification_eligible": (
                    self.sequence_gaps == 0
                    and self.reconnects == 0
                    and self.bridged
                    and self.trade_count > 0
                    and self.mark_count > 0
                ),
            }
            (self.out / "manifest.json").write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
        finally:
            self.events_file.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=1800)
    parser.add_argument("--output-root", type=Path, default=Path("data/captures"))
    args = parser.parse_args()

    session = args.output_root / (
        time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8]
    )
    Capture(session, args.duration).run()
    print(session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
