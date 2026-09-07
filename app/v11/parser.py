"""V11 data parser — converts raw Binance websocket events to structured order book and trade data.

Reads the v10.raw.v1 schema (events.jsonl + snapshot.json) and produces:
  - BookState snapshots at each depth event
  - Trade records with aggressor side
  - Mid-price series for target computation

All parsing is causal: features use only data available at event time.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd


@dataclass
class TradeRecord:
    ts_ms: int
    price: float
    qty: float
    aggressor_side: Literal["BUY", "SELL"]
    buyer_is_maker: bool


@dataclass
class BookSnapshot:
    ts_ms: int
    best_bid: float | None
    best_ask: float | None
    mid: float | None
    spread_bps: float | None
    bids: dict[float, float]
    asks: dict[float, float]
    bid_depth1: float
    ask_depth1: float
    bid_depth5: float
    ask_depth5: float
    bid_depth10: float
    ask_depth10: float
    qi1: float
    qi5: float
    qi10: float
    ofi_l1: float
    ofi_l5: float
    ofi_l10: float
    adds: float
    cancels: float
    net: float
    buy_vol: float
    sell_vol: float
    tfi: float


class V11DataParser:
    """Parse v10.raw.v1 schema into structured data."""

    def __init__(self, session_dir: Path):
        self.session_dir = Path(session_dir)
        self.snapshot_path = self.session_dir / "snapshot.json"
        self.events_path = self.session_dir / "events.jsonl"
        self.manifest_path = self.session_dir / "manifest.json"

    def parse(self) -> tuple[list[BookSnapshot], list[TradeRecord]]:
        """Parse session into book snapshots and trades."""
        with open(self.snapshot_path) as f:
            snap = json.load(f)

        bids0 = {float(p): float(q) for p, q in snap["bids"]}
        asks0 = {float(p): float(q) for p, q in snap["asks"]}

        books: list[BookSnapshot] = []
        trades: list[TradeRecord] = []
        prev_bids = dict(bids0)
        prev_asks = dict(asks0)
        trade_buffer: list[dict] = []
        window_ms = 1000

        with open(self.events_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                ev_type = rec.get("event_type")
                ev_time_ms = rec.get("event_time_ms")
                if ev_time_ms is None:
                    continue
                raw_str = rec.get("raw_json", "")
                if not raw_str:
                    continue
                try:
                    raw = json.loads(raw_str)
                except json.JSONDecodeError:
                    continue
                data = raw.get("data", raw)

                if ev_type == "depthUpdate":
                    b_list = [(float(p), float(q)) for p, q in data.get("b", [])]
                    a_list = [(float(p), float(q)) for p, q in data.get("a", [])]
                    cur_bids = {p: q for p, q in b_list}
                    cur_asks = {p: q for p, q in a_list}

                    bid_l1 = bid_l5 = bid_l10 = 0.0
                    ask_l1 = ask_l5 = ask_l10 = 0.0
                    top_b = sorted(cur_bids.items(), reverse=True)[:10]
                    top_a = sorted(cur_asks.items())[:10]
                    for i, (p, q) in enumerate(top_b):
                        if i < 1: bid_l1 += q
                        if i < 5: bid_l5 += q
                        if i < 10: bid_l10 += q
                    for i, (p, q) in enumerate(top_a):
                        if i < 1: ask_l1 += q
                        if i < 5: ask_l5 += q
                        if i < 10: ask_l10 += q

                    adds = cancels = net = 0.0
                    for p, q in cur_bids.items():
                        old = prev_bids.get(p, 0.0)
                        d = q - old
                        if q > 0 and old == 0:
                            adds += q
                        elif q == 0 and old > 0:
                            cancels += old
                        net += d
                    for p, q in cur_asks.items():
                        old = prev_asks.get(p, 0.0)
                        d = q - old
                        if q > 0 and old == 0:
                            adds += q
                        elif q == 0 and old > 0:
                            cancels += old
                        net -= d

                    ofi_l1 = bid_l1 - ask_l1
                    ofi_l5 = bid_l5 - ask_l5
                    ofi_l10 = bid_l10 - ask_l10

                    best_bid = top_b[0][0] if top_b else None
                    best_ask = top_a[0][0] if top_a else None
                    mid = (best_bid + best_ask) / 2.0 if (best_bid is not None and best_ask is not None) else None
                    spread_bps = ((best_ask - best_bid) / mid * 1e4) if (mid and best_bid is not None) else None
                    qi1 = (bid_l1 - ask_l1) / (bid_l1 + ask_l1) if (bid_l1 + ask_l1) else 0.0
                    qi5 = (bid_l5 - ask_l5) / (bid_l5 + ask_l5) if (bid_l5 + ask_l5) else 0.0
                    qi10 = (bid_l10 - ask_l10) / (bid_l10 + ask_l10) if (bid_l10 + ask_l10) else 0.0

                    # flush trades in window
                    while trade_buffer and ev_time_ms - trade_buffer[0]["ts_ms"] > window_ms:
                        trade_buffer.pop(0)
                    buy_vol = sum(t["qty"] for t in trade_buffer if t["side"] == "BUY")
                    sell_vol = sum(t["qty"] for t in trade_buffer if t["side"] == "SELL")
                    tot = buy_vol + sell_vol
                    tfi = (buy_vol - sell_vol) / tot if tot else 0.0

                    books.append(BookSnapshot(
                        ts_ms=ev_time_ms,
                        best_bid=best_bid,
                        best_ask=best_ask,
                        mid=mid,
                        spread_bps=spread_bps,
                        bids=cur_bids,
                        asks=cur_asks,
                        bid_depth1=bid_l1,
                        ask_depth1=ask_l1,
                        bid_depth5=bid_l5,
                        ask_depth5=ask_l5,
                        bid_depth10=bid_l10,
                        ask_depth10=ask_l10,
                        qi1=qi1,
                        qi5=qi5,
                        qi10=qi10,
                        ofi_l1=ofi_l1,
                        ofi_l5=ofi_l5,
                        ofi_l10=ofi_l10,
                        adds=adds,
                        cancels=cancels,
                        net=net,
                        buy_vol=buy_vol,
                        sell_vol=sell_vol,
                        tfi=tfi,
                    ))
                    prev_bids = cur_bids
                    prev_asks = cur_asks

                elif ev_type == "bookTicker":
                    # bookTicker gives best bid/ask; use as reference
                    pass

                elif ev_type == "trade":
                    price = float(data.get("p", 0))
                    qty = float(data.get("q", 0))
                    buyer_is_maker = bool(data.get("m", False))
                    side = "SELL" if buyer_is_maker else "BUY"
                    trade_buffer.append({
                        "ts_ms": ev_time_ms,
                        "price": price,
                        "qty": qty,
                        "side": side,
                        "buyer_is_maker": buyer_is_maker,
                    })
                    trades.append(TradeRecord(
                        ts_ms=ev_time_ms,
                        price=price,
                        qty=qty,
                        aggressor_side=side,
                        buyer_is_maker=buyer_is_maker,
                    ))

        return books, trades
