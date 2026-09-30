#!/usr/bin/env python3
"""Capture authentic BTCUSDT USDⓈ-M perpetual market data.

Research infrastructure only. This script never places orders.

Captured streams:
  - BTCUSDT depth@100ms
  - BTCUSDT aggTrade
  - BTCUSDT markPrice@1s (mark price + current funding information)

The raw events are preserved verbatim in events.jsonl. A REST depth snapshot
is acquired after the WebSocket buffer starts so the snapshot can be bridged
to the first valid depth update. Any sequence discontinuity after the bridge
terminates the capture instead of producing a silently invalid dataset.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import threading
import time
import uuid

import requests
import websocket


SYMBOL = "BTCUSDT"
WS_BASE = "wss://fstream.binance.com/stream?streams="
REST_BASE = "https://fapi.binance.com"


class Capture:
    def __init__(self, out: Path, duration_s: int) -> None:
        self.out = out
        self.duration_s = duration_s
        self.out.mkdir(parents=True, exist_ok=False)
        self.events_path = self.out / "events.jsonl"
        self.snapshot_path = self.out / "snapshot.json"
        self.lock = threading.Lock()
        self.started_ns = time.time_ns()
        self.stopped = threading.Event()
        self.buffer: list[dict] = []
        self.snapshot_last_id: int | None = None
        self.bridged = False
        self.previous_u: int | None = None
        self.event_count = 0
        self.depth_count = 0
        self.trade_count = 0
        self.mark_count = 0
        self.sequence_gaps = 0
        self.reconnects = 0

    def write_row(self, event_type: str, raw: str, **extra) -> None:
        row = {
            "event_type": event_type,
            "received_ns": time.time_ns(),
            "raw_json": raw,
            **extra,
        }
        with self.lock, self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")
            fh.flush()
        self.event_count += 1

    def fetch_snapshot(self) -> None:
        r = requests.get(
            f"{REST_BASE}/fapi/v1/depth",
            params={"symbol": SYMBOL, "limit": 1000},
            timeout=10,
        )
        r.raise_for_status()
        payload = r.json()
        if not payload.get("lastUpdateId"):
            raise RuntimeError("invalid BTCUSDT futures depth snapshot")
        self.snapshot_last_id = int(payload["lastUpdateId"])
        self.snapshot_path.write_text(
            json.dumps(
                {
                    "T": int(time.time() * 1000),
                    "lastUpdateId": self.snapshot_last_id,
                    "bids": payload["bids"],
                    "asks": payload["asks"],
                },
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )

    def process_depth(self, raw: str, data: dict) -> None:
        U = int(data["U"])
        u = int(data["u"])
        pu = int(data.get("pu", 0))

        if not self.bridged:
            if self.snapshot_last_id is None:
                self.buffer.append({"raw": raw, "data": data})
                return
            if not (U <= self.snapshot_last_id <= u):
                self.buffer.append({"raw": raw, "data": data})
                return

            self.bridged = True
            self.previous_u = u
            self.depth_count += 1
            self.write_row("depthUpdate", raw)
            buffered = list(self.buffer)
            self.buffer.clear()
            for item in buffered:
                self.process_depth(item["raw"], item["data"])
            return

        if pu and self.previous_u is not None and pu != self.previous_u:
            self.sequence_gaps += 1
            raise RuntimeError(
                f"BTCUSDT futures L2 sequence gap: expected pu={self.previous_u}, got {pu}"
            )

        self.previous_u = u
        self.depth_count += 1
        self.write_row("depthUpdate", raw)

    def on_message(self, _ws, raw: str) -> None:
        envelope = json.loads(raw)
        data = envelope.get("data", envelope)
        event = data.get("e")

        if event == "depthUpdate":
            self.process_depth(raw, data)
        elif event == "aggTrade":
            self.trade_count += 1
            self.write_row("aggTrade", raw)
        elif event == "markPriceUpdate":
            # Contains mark price and current funding-rate information.
            self.mark_count += 1
            self.write_row("markPriceUpdate", raw)

    def on_error(self, _ws, error) -> None:
        self.stopped.set()
        raise RuntimeError(f"WebSocket error: {error}")

    def on_close(self, _ws, _code, _msg) -> None:
        if not self.stopped.is_set():
            self.reconnects += 1
            self.write_row("reconnect", json.dumps({"reason": "websocket_closed"}))
            self.stopped.set()

    def run(self) -> None:
        streams = (
            f"{SYMBOL.lower()}@depth@100ms/"
            f"{SYMBOL.lower()}@aggTrade/"
            f"{SYMBOL.lower()}@markPrice@1s"
        )
        url = WS_BASE + streams

        ws = websocket.WebSocketApp(
            url,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
        )
        thread = threading.Thread(
            target=lambda: ws.run_forever(ping_interval=20, ping_timeout=10),
            daemon=True,
        )
        thread.start()

        time.sleep(0.25)
        self.fetch_snapshot()

        deadline = time.monotonic() + self.duration_s
        while time.monotonic() < deadline and not self.stopped.is_set():
            if self.bridged:
                time.sleep(0.25)
            else:
                time.sleep(0.05)

        self.stopped.set()
        ws.close()
        thread.join(timeout=5)

        if not self.bridged:
            raise RuntimeError("capture ended without a valid snapshot/depth bridge")

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
            },
            "certification_eligible": self.sequence_gaps == 0 and self.reconnects == 0,
        }
        (self.out / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )


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
