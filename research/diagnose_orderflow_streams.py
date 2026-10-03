#!/usr/bin/env python3
"""Short transport diagnostic for ORDERFLOW_STATE_TRANSITION-0.1.

This is a non-research connectivity check. It opens one raw Binance WebSocket
per required BTCUSDT market-data feed and requires at least one valid event
from each feed. No captures are written and no trading/account access occurs.
"""

from __future__ import annotations

import asyncio
import json
import time

import websockets


DURATION_SEC = 20
STREAMS = {
    "depth": "wss://fstream.binance.com/public/ws/btcusdt@depth@100ms",
    "aggTrade": "wss://fstream.binance.com/market/ws/btcusdt@aggTrade",
    "markPrice": "wss://fstream.binance.com/market/ws/btcusdt@markPrice@1s",
}


def valid(feed: str, data: object) -> bool:
    if not isinstance(data, dict) or data.get("s") != "BTCUSDT":
        return False
    if feed == "depth":
        return all(k in data for k in ("U", "u", "b", "a", "E"))
    if feed == "aggTrade":
        return all(k in data for k in ("a", "p", "q", "T", "E", "m"))
    return all(k in data for k in ("p", "r", "E"))


async def probe(feed: str, url: str, deadline: float) -> tuple[str, int, str | None]:
    count = 0
    first = None
    try:
        async with websockets.connect(
            url,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=10,
            max_size=4 * 1024 * 1024,
        ) as ws:
            while time.monotonic() < deadline:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
                data = json.loads(raw)
                if not valid(feed, data):
                    continue
                count += 1
                if first is None:
                    first = json.dumps(data, separators=(",", ":"), sort_keys=True)
                    break
    except Exception as exc:
        return feed, count, f"{type(exc).__name__}: {exc}"
    return feed, count, first


async def main() -> int:
    deadline = time.monotonic() + DURATION_SEC
    results = await asyncio.gather(
        *(probe(feed, url, deadline) for feed, url in STREAMS.items())
    )

    failed = False
    for feed, count, detail in results:
        print(f"{feed}: valid_events={count}")
        if detail:
            print(f"{feed}: {detail}")
        if count < 1:
            failed = True

    print("PASS raw-feed transport diagnostic" if not failed else "FAIL raw-feed transport diagnostic")
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
