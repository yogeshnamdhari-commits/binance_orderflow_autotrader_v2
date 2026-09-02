"""Synthetic Binance USD-M capture generator for V10 empirical integration tests.

Produces deterministic, realistic BTCUSDT perpetual market-data events that
conform to the Binance WebSocket stream schema used by the V10 recorder.
This is research-only test data, not real market data.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from app.v10_market_data import SessionRecorder


@dataclass(frozen=True)
class _DepthLevel:
    price: float
    qty: float


def _round_price(price: float, tick: float = 0.1) -> float:
    return round(round(price / tick) * tick, 1)


def _round_qty(qty: float, step: float = 0.001) -> float:
    return round(round(qty / step) * step, 3)


def generate_synthetic_capture(
    output_dir: str | Path,
    *,
    session_id: str = "synthetic_btcusdt_001",
    n_depth_events: int = 200,
    n_trades: int = 80,
    start_mid: float = 65000.0,
    tick_size: float = 0.1,
    qty_step: float = 0.001,
    seed: int = 42,
) -> Path:
    """Generate a deterministic synthetic BTCUSDT capture session.

    The generator produces a realistic sequence of depth updates and trades
    with proper Binance sequencing (U, u, pu continuity). It writes the
    session using the real V10 SessionRecorder so the output is indistinguishable
    from a real capture session.
    """
    import random

    rng = random.Random(seed)

    streams = ["btcusdt@depth@100ms", "btcusdt@trade", "btcusdt@bookTicker"]
    recorder = SessionRecorder(output_dir, "BTCUSDT", streams, session_id=session_id)
    session_dir = recorder.start(start_ns=1_000_000_000_000)

    mid = float(start_mid)
    update_id = 1000
    trade_id = 5000
    event_time_ms = 1_700_000_000_000
    previous_u = 999

    bids: list[_DepthLevel] = []
    asks: list[_DepthLevel] = []

    for i in range(20):
        bids.append(_DepthLevel(_round_price(mid - tick_size * (i + 1), tick_size), _round_qty(rng.uniform(0.5, 5.0), qty_step)))
        asks.append(_DepthLevel(_round_price(mid + tick_size * (i + 1), tick_size), _round_qty(rng.uniform(0.5, 5.0), qty_step)))

    def _snapshot() -> dict:
        return {
            "lastUpdateId": update_id,
            "bids": [[b.price, b.qty] for b in bids],
            "asks": [[a.price, a.qty] for a in asks],
        }

    def _depth_event(U: int, u: int, pu: int, b_updates: list[list[float]], a_updates: list[list[float]]) -> str:
        return json.dumps({
            "stream": "btcusdt@depth@100ms",
            "data": {
                "e": "depthUpdate",
                "E": event_time_ms,
                "s": "BTCUSDT",
                "U": U,
                "u": u,
                "pu": pu,
                "b": b_updates,
                "a": a_updates,
            },
        })

    def _trade_event(price: float, qty: float, buyer_is_maker: bool) -> str:
        return json.dumps({
            "stream": "btcusdt@trade",
            "data": {
                "e": "trade",
                "E": event_time_ms,
                "s": "BTCUSDT",
                "t": trade_id,
                "p": f"{price:.1f}",
                "q": f"{qty:.3f}",
                "T": event_time_ms,
                "m": buyer_is_maker,
            },
        })

    def _book_ticker_event() -> str:
        return json.dumps({
            "stream": "btcusdt@bookTicker",
            "data": {
                "e": "bookTicker",
                "E": event_time_ms,
                "s": "BTCUSDT",
                "b": f"{bids[0].price:.1f}",
                "B": f"{bids[0].qty:.3f}",
                "a": f"{asks[0].price:.1f}",
                "A": f"{asks[0].qty:.3f}",
            },
        })

    depth_idx = 0
    trade_idx = 0

    while depth_idx < n_depth_events or trade_idx < n_trades:
        if depth_idx < n_depth_events and (trade_idx >= n_trades or rng.random() < 0.7):
            U = update_id + 1
            n_updates = rng.randint(1, 3)
            u = U + n_updates - 1
            pu = previous_u

            b_updates: list[list[float]] = []
            a_updates: list[list[float]] = []

            for _ in range(n_updates):
                if rng.random() < 0.3 and bids:
                    level = rng.randint(0, min(4, len(bids) - 1))
                    new_qty = _round_qty(max(0.0, bids[level].qty + rng.uniform(-0.5, 0.5)), qty_step)
                    b_updates.append([bids[level].price, new_qty])
                    bids[level] = _DepthLevel(bids[level].price, new_qty)
                elif rng.random() < 0.5 and asks:
                    level = rng.randint(0, min(4, len(asks) - 1))
                    new_qty = _round_qty(max(0.0, asks[level].qty + rng.uniform(-0.5, 0.5)), qty_step)
                    a_updates.append([asks[level].price, new_qty])
                    asks[level] = _DepthLevel(asks[level].price, new_qty)
                elif rng.random() < 0.5 and bids:
                    level = rng.randint(0, min(2, len(bids) - 1))
                    new_qty = _round_qty(rng.uniform(0.1, 3.0), qty_step)
                    b_updates.append([bids[level].price, new_qty])
                    bids[level] = _DepthLevel(bids[level].price, new_qty)
                elif asks:
                    level = rng.randint(0, min(2, len(asks) - 1))
                    new_qty = _round_qty(rng.uniform(0.1, 3.0), qty_step)
                    a_updates.append([asks[level].price, new_qty])
                    asks[level] = _DepthLevel(asks[level].price, new_qty)

            if not b_updates and not a_updates:
                if bids:
                    b_updates.append([bids[0].price, _round_qty(bids[0].qty, qty_step)])
                if asks:
                    a_updates.append([asks[0].price, _round_qty(asks[0].qty, qty_step)])

            recorder.record_raw(_depth_event(U, u, pu, b_updates, a_updates), receive_ns=event_time_ms * 1_000_000)
            previous_u = u
            update_id = u
            event_time_ms += rng.randint(90, 110)
            depth_idx += 1

            if depth_idx % 10 == 0:
                recorder.record_raw(_book_ticker_event(), receive_ns=event_time_ms * 1_000_000)

        elif trade_idx < n_trades:
            side = rng.choice(["buy", "sell"])
            price = 0.0
            qty = 0.0
            buyer_is_maker = False
            if side == "buy" and asks:
                price = asks[0].price
                qty = _round_qty(max(qty_step, min(asks[0].qty, rng.uniform(0.01, 2.0))), qty_step)
                buyer_is_maker = False
                asks[0] = _DepthLevel(asks[0].price, _round_qty(max(0, asks[0].qty - qty), qty_step))
                if asks[0].qty <= 0:
                    asks.pop(0)
                    if len(asks) < 20:
                        asks.append(_DepthLevel(_round_price(asks[-1].price + tick_size, tick_size), _round_qty(rng.uniform(0.5, 5.0), qty_step)))
            elif side == "sell" and bids:
                price = bids[0].price
                qty = _round_qty(max(qty_step, min(bids[0].qty, rng.uniform(0.01, 2.0))), qty_step)
                buyer_is_maker = True
                bids[0] = _DepthLevel(bids[0].price, _round_qty(max(0, bids[0].qty - qty), qty_step))
                if bids[0].qty <= 0:
                    bids.pop(0)
                    if len(bids) < 20:
                        bids.append(_DepthLevel(_round_price(bids[-1].price - tick_size, tick_size), _round_qty(rng.uniform(0.5, 5.0), qty_step)))
            else:
                continue

            recorder.record_raw(_trade_event(price, qty, buyer_is_maker), receive_ns=event_time_ms * 1_000_000)
            trade_id += 1
            event_time_ms += rng.randint(50, 200)
            trade_idx += 1

    recorder.close(end_ns=event_time_ms * 1_000_000)
    return session_dir
