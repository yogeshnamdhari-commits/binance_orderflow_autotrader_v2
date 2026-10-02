#!/usr/bin/env python3
"""Fresh BTCUSDT capture for ORDERFLOW_STATE_TRANSITION-0.1.

Research-only. No trading/account access is used.

The collector records:
- raw Binance depth@100ms / aggTrade / markPrice@1s messages
- the initial REST depth snapshot
- reconstructed top-10 book snapshots after each valid depth update
- integrity/sequence metadata
- SHA-256 fingerprints for the files

Run one capture at a time:
  python research/collect_orderflow_state_transition.py --capture 1
  python research/collect_orderflow_state_transition.py --capture 2
  python research/collect_orderflow_state_transition.py --capture 3

Capture 1 is development-only. Captures 2 and 3 are untouched OOS.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiohttp
import websockets


SYMBOL = "BTCUSDT"
DURATION_SEC = 60 * 60
DEPTH_LEVELS = 10
REST_LIMIT = 1000

WS_URL = (
    "wss://fstream.binance.com/stream"
    "?streams=btcusdt@depth@100ms/"
    "btcusdt@aggTrade/"
    "btcusdt@markPrice@1s"
)
REST_URL = "https://fapi.binance.com/fapi/v1/depth"

ROOT = Path(__file__).resolve().parents[2]
OUT_ROOT = ROOT / "research" / "captures" / "ORDERFLOW_STATE_TRANSITION_01"


@dataclass
class BookState:
    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)
    last_update_id: int | None = None
    updates_applied: int = 0
    sequence_gaps: int = 0

    def replace_from_snapshot(self, payload: dict[str, Any]) -> None:
        self.bids = {
            float(p): float(q)
            for p, q in payload.get("bids", [])
            if float(q) > 0
        }
        self.asks = {
            float(p): float(q)
            for p, q in payload.get("asks", [])
            if float(q) > 0
        }
        self.last_update_id = int(payload["lastUpdateId"])

    def apply_delta(self, payload: dict[str, Any]) -> None:
        for p, q in payload.get("b", []):
            price, qty = float(p), float(q)
            if qty == 0:
                self.bids.pop(price, None)
            else:
                self.bids[price] = qty
        for p, q in payload.get("a", []):
            price, qty = float(p), float(q)
            if qty == 0:
                self.asks.pop(price, None)
            else:
                self.asks[price] = qty

        self.last_update_id = int(payload["u"])
        self.updates_applied += 1

    def top_n(self) -> tuple[list[list[float]], list[list[float]]]:
        bids = sorted(self.bids.items(), key=lambda x: x[0], reverse=True)[:DEPTH_LEVELS]
        asks = sorted(self.asks.items(), key=lambda x: x[0])[:DEPTH_LEVELS]
        return [[p, q] for p, q in bids], [[p, q] for p, q in asks]


@dataclass
class Integrity:
    connected_at_ms: int = 0
    first_message_ms: int = 0
    stopped_at_ms: int = 0
    reconnects: int = 0
    sequence_gaps: int = 0
    malformed_events: int = 0
    missing_feed_events: int = 0
    bridged: bool = False
    bridge_first_u: int | None = None
    bridge_snapshot_last_update_id: int | None = None
    last_depth_u: int | None = None
    depth_events: int = 0
    trade_events: int = 0
    mark_events: int = 0


class JsonlWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.fp = path.open("w", encoding="utf-8")

    def write(self, record: dict[str, Any]) -> None:
        self.fp.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")
        self.fp.flush()

    def close(self) -> None:
        self.fp.flush()
        self.fp.close()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def fetch_snapshot(session: aiohttp.ClientSession) -> dict[str, Any]:
    async with session.get(
        REST_URL,
        params={"symbol": SYMBOL, "limit": REST_LIMIT},
    ) as resp:
        resp.raise_for_status()
        return await resp.json()


def validate_common_event(data: dict[str, Any], feed: str) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("s") != SYMBOL:
        return False
    if feed == "depth":
        return all(k in data for k in ("U", "u", "b", "a"))
    if feed == "aggTrade":
        return all(k in data for k in ("a", "p", "q", "T", "m"))
    if feed == "markPrice":
        return all(k in data for k in ("p", "r", "E"))
    return False


async def capture(capture_no: int) -> int:
    started_wall_ms = int(time.time() * 1000)
    out_dir = OUT_ROOT / f"capture_{capture_no}"
    out_dir.mkdir(parents=True, exist_ok=False)

    raw_path = out_dir / "events.jsonl"
    book_path = out_dir / "book_snapshots.jsonl"
    manifest_path = out_dir / "manifest.json"

    raw = JsonlWriter(raw_path)
    books = JsonlWriter(book_path)
    integrity = Integrity()
    book = BookState()

    stop_event = asyncio.Event()

    def request_stop() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_stop)
        except (NotImplementedError, RuntimeError):
            pass

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=15)
    ) as session:
        integrity.connected_at_ms = int(time.time() * 1000)

        try:
            async with websockets.connect(
                WS_URL,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=10,
                max_size=4 * 1024 * 1024,
            ) as ws:
                integrity.first_message_ms = int(time.time() * 1000)

                # Critical bridge procedure:
                # 1) connect and buffer depth events
                # 2) obtain REST snapshot
                # 3) discard events fully covered by snapshot
                # 4) first applied event must satisfy U <= snapshot+1 <= u
                snapshot = await fetch_snapshot(session)
                snapshot_id = int(snapshot["lastUpdateId"])
                book.replace_from_snapshot(snapshot)
                integrity.bridge_snapshot_last_update_id = snapshot_id

                start_monotonic = time.monotonic()
                while (
                    not stop_event.is_set()
                    and time.monotonic() - start_monotonic < DURATION_SEC
                ):
                    timeout = max(
                        0.5,
                        min(5.0, DURATION_SEC - (time.monotonic() - start_monotonic)),
                    )
                    try:
                        raw_msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    except asyncio.TimeoutError:
                        continue

                    received_ms = int(time.time() * 1000)
                    try:
                        msg = json.loads(raw_msg)
                        data = msg.get("data", {})
                        stream = msg.get("stream", "")
                    except (json.JSONDecodeError, AttributeError):
                        integrity.malformed_events += 1
                        continue

                    if not data:
                        integrity.missing_feed_events += 1
                        continue

                    if integrity.first_message_ms == 0:
                        integrity.first_message_ms = received_ms

                    if "@depth@" in stream:
                        feed = "depth"
                    elif "@aggTrade" in stream:
                        feed = "aggTrade"
                    elif "@markPrice@1s" in stream:
                        feed = "markPrice"
                    else:
                        continue

                    if not validate_common_event(data, feed):
                        integrity.malformed_events += 1
                        continue

                    # Keep the exact exchange message plus local receive timestamp.
                    raw.write(
                        {
                            "capture": capture_no,
                            "received_ts_ms": received_ms,
                            "exchange_event": data.get("E"),
                            "feed": feed,
                            "source": "binance",
                            "symbol": SYMBOL,
                            "synthetic": False,
                            "data": data,
                        }
                    )

                    if feed == "aggTrade":
                        integrity.trade_events += 1
                        continue

                    if feed == "markPrice":
                        integrity.mark_events += 1
                        continue

                    integrity.depth_events += 1
                    U = int(data["U"])
                    u = int(data["u"])
                    pu = data.get("pu")

                    if not integrity.bridged:
                        if u <= snapshot_id:
                            # Event is entirely covered by REST snapshot.
                            continue
                        if U <= snapshot_id + 1 <= u:
                            book.apply_delta(data)
                            integrity.bridged = True
                            integrity.bridge_first_u = U
                            integrity.last_depth_u = u
                        else:
                            # We cannot safely reconstruct the book.
                            integrity.sequence_gaps += 1
                            break
                    else:
                        if pu is not None:
                            if int(pu) != int(book.last_update_id):
                                integrity.sequence_gaps += 1
                                break
                        elif U != int(book.last_update_id) + 1:
                            integrity.sequence_gaps += 1
                            break
                        book.apply_delta(data)
                        integrity.last_depth_u = u

                    if integrity.bridged and integrity.sequence_gaps == 0:
                        bids, asks = book.top_n()
                        if not bids or not asks:
                            integrity.malformed_events += 1
                            break
                        books.write(
                            {
                                "capture": capture_no,
                                "timestamp_event_ms": int(data["E"]),
                                "timestamp_transaction_ms": int(
                                    data.get("T", data["E"])
                                ),
                                "received_ts_ms": received_ms,
                                "source": "binance",
                                "feed": "depth@100ms",
                                "symbol": SYMBOL,
                                "synthetic": False,
                                "last_update_id": int(book.last_update_id),
                                "bids": bids,
                                "asks": asks,
                            }
                        )

                integrity.stopped_at_ms = int(time.time() * 1000)

        finally:
            raw.close()
            books.close()

    manifest = {
        "hypothesis_id": "ORDERFLOW_STATE_TRANSITION-0.1",
        "capture": capture_no,
        "capture_role": "development" if capture_no == 1 else "untouched_oos",
        "symbol": SYMBOL,
        "market": "Binance USD-M Futures",
        "contract": "PERPETUAL",
        "duration_target_sec": DURATION_SEC,
        "started_wall_ms": started_wall_ms,
        "stopped_wall_ms": integrity.stopped_at_ms,
        "ws_url": WS_URL,
        "rest_url": REST_URL,
        "required_feeds": [
            "depth@100ms",
            "aggTrade",
            "markPrice@1s",
        ],
        "integrity": integrity.__dict__,
        "economic_model_version": "A-001",
        "reference_notional_usdt": 100.0,
        "entry_taker_fee_bps": 5.0,
        "exit_taker_fee_bps": 5.0,
        "round_trip_taker_fee_bps": 10.0,
        "safety_buffer_bps": 2.0,
        "execution_benchmark": "first_book_snapshot_after_signal_then_book_snapshot_at_or_after_5s; depth-VWAP_for_100USDT",
        "funding": "realized_only_if_5s_hold_crosses_settlement; use_markPrice_rate_immediately_before_settlement",
        "live_order_submission": False,
        "deployment": "NO_DEPLOY",
        "files": {},
    }

    manifest["files"]["events.jsonl"] = {
        "sha256": sha256_file(raw_path),
        "bytes": raw_path.stat().st_size,
    }
    manifest["files"]["book_snapshots.jsonl"] = {
        "sha256": sha256_file(book_path),
        "bytes": book_path.stat().st_size,
    }

    # Fail closed: a captured session is not valid evidence unless the order
    # book bridge completed and the session had no sequence gap/reconnect.
    manifest["capture_valid"] = bool(
        integrity.bridged
        and integrity.sequence_gaps == 0
        and integrity.reconnects == 0
        and integrity.malformed_events == 0
        and integrity.depth_events > 0
        and integrity.trade_events > 0
        and integrity.mark_events > 0
    )

    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if manifest["capture_valid"] else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", type=int, choices=(1, 2, 3), required=True)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(capture(parse_args().capture)))
