"""Build a leakage-safe V21 order-flow feature/label dataset.

The dataset is generated from authentic Binance captures only. Features are
computed from book/trade information available at timestamp t; labels use only
strictly future mid prices.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from app.mm.book import OrderBook
from app.mm.execution_replay import Side, TradeEvent
from scripts.v20_event_backtest_capture import load_events, load_snapshot


TICK_SIZE = 0.1
HORIZONS_MS = (100, 250, 500, 1000)
WINDOWS_MS = (100, 250, 500, 1000)


@dataclass(frozen=True)
class Sample:
    timestamp_ms: int
    session: str
    half: int
    mid: float
    spread_bps: float
    tick_size: float
    queue_imbalance: float
    microprice_edge_bps: float
    ofi_100ms: float
    ofi_500ms: float
    ofi_1000ms: float
    trade_imbalance_100ms: float
    trade_imbalance_500ms: float
    trade_imbalance_1000ms: float
    trade_intensity_notional_s: float
    mid_return_100ms_bps: float
    mid_return_500ms_bps: float
    depth_5_imbalance: float


FEATURES = [
    "queue_imbalance",
    "microprice_edge_bps",
    "ofi_100ms",
    "ofi_500ms",
    "ofi_1000ms",
    "trade_imbalance_100ms",
    "trade_imbalance_500ms",
    "trade_imbalance_1000ms",
    "trade_intensity_notional_s",
    "spread_bps",
    "mid_return_100ms_bps",
    "mid_return_500ms_bps",
    "depth_5_imbalance",
]


def _trade_imbalance(trades: deque[tuple[int, float]], now: int, window: int) -> float:
    cutoff = now - window
    signed = 0.0
    absolute = 0.0
    for ts, qty in trades:
        if ts >= cutoff:
            signed += qty
            absolute += abs(qty)
    return signed / absolute if absolute > 0 else 0.0


def _trade_notional_rate(trades: deque[tuple[int, float, float]], now: int, window: int = 1000) -> float:
    cutoff = now - window
    notional = sum(n for ts, _, n in trades if ts >= cutoff)
    return notional * 1000.0 / window


def _past_mid(mid_history: deque[tuple[int, float]], now: int, window: int) -> float | None:
    target = now - window
    candidate = None
    for ts, mid in mid_history:
        if ts > target:
            break
        candidate = mid
    return candidate


def _future_mid(times: list[int], mids: list[float], now_ms: int, horizon_ms: int) -> float | None:
    idx = bisect_left(times, now_ms + horizon_ms)
    if idx >= len(mids):
        return None
    return mids[idx]


def _features_from_book(
    book: OrderBook,
    now_ms: int,
    session: str,
    half: int,
    ofi_history: deque[tuple[int, float]],
    trade_history: deque[tuple[int, float, float]],
    mid_history: deque[tuple[int, float]],
) -> Sample | None:
    bids = book.get_depth("bid", levels=5)
    asks = book.get_depth("ask", levels=5)
    if not bids or not asks:
        return None
    best_bid, bid_qty = bids[0]
    best_ask, ask_qty = asks[0]
    mid = (best_bid + best_ask) / 2.0
    if not (best_bid > 0 and best_ask > best_bid and mid > 0):
        return None

    spread_bps = (best_ask - best_bid) * 10_000.0 / mid
    qi_den = bid_qty + ask_qty
    qi = (bid_qty - ask_qty) / qi_den if qi_den > 0 else 0.0
    micro = (best_ask * bid_qty + best_bid * ask_qty) / qi_den if qi_den > 0 else mid
    micro_edge = (micro - mid) * 10_000.0 / mid

    bid5 = sum(q for _, q in bids)
    ask5 = sum(q for _, q in asks)
    depth5_imb = (bid5 - ask5) / (bid5 + ask5) if (bid5 + ask5) > 0 else 0.0

    def rolling_ofi(window: int) -> float:
        cutoff = now_ms - window
        return sum(v for ts, v in ofi_history if ts >= cutoff)

    past100 = _past_mid(mid_history, now_ms, 100)
    past500 = _past_mid(mid_history, now_ms, 500)
    ret100 = (mid / past100 - 1.0) * 10_000.0 if past100 and past100 > 0 else 0.0
    ret500 = (mid / past500 - 1.0) * 10_000.0 if past500 and past500 > 0 else 0.0

    return Sample(
        timestamp_ms=now_ms,
        session=session,
        half=half,
        mid=mid,
        spread_bps=spread_bps,
        tick_size=TICK_SIZE,
        queue_imbalance=qi,
        microprice_edge_bps=micro_edge,
        ofi_100ms=rolling_ofi(100),
        ofi_500ms=rolling_ofi(500),
        ofi_1000ms=rolling_ofi(1000),
        trade_imbalance_100ms=_trade_imbalance(trade_history, now_ms, 100),
        trade_imbalance_500ms=_trade_imbalance(trade_history, now_ms, 500),
        trade_imbalance_1000ms=_trade_imbalance(trade_history, now_ms, 1000),
        trade_intensity_notional_s=_trade_notional_rate(trade_history, now_ms),
        mid_return_100ms_bps=ret100,
        mid_return_500ms_bps=ret500,
        depth_5_imbalance=depth5_imb,
    )


def extract_session(capture_dir: Path, session: str) -> pd.DataFrame:
    snapshot = load_snapshot(capture_dir)
    depth, trades, counts = load_events(capture_dir)
    if counts["depth_events"] < 500 or counts["trade_events"] < 500:
        raise ValueError(f"{session}: insufficient market events")

    all_mid_times: list[int] = []
    all_mids: list[float] = []
    future_book = OrderBook.from_snapshot(snapshot)
    for event in sorted(depth, key=lambda e: (e.timestamp_ns, e.final_update_id)):
        future_book.apply_update(event)
        mid = future_book.get_mid_price()
        if mid > 0:
            all_mid_times.append(event.timestamp_ns // 1_000_000)
            all_mids.append(mid)

    session_midpoint = (all_mid_times[0] + all_mid_times[-1]) // 2

    book = OrderBook.from_snapshot(snapshot)
    previous_bid: tuple[float, float] | None = None
    previous_ask: tuple[float, float] | None = None
    ofi_history: deque[tuple[int, float]] = deque()
    trade_history: deque[tuple[int, float, float]] = deque()
    mid_history: deque[tuple[int, float]] = deque()
    samples: list[dict[str, Any]] = []

    merged: list[tuple[int, int, object]] = []
    merged.extend((e.timestamp_ns, 0, e) for e in depth)
    merged.extend((e.timestamp_ns, 1, e) for e in trades)
    merged.sort(key=lambda x: (x[0], x[1]))

    for ts_ns, kind, event in merged:
        now = ts_ns // 1_000_000
        if kind == 1:
            trade = event
            signed_qty = float(trade.qty) if trade.aggressor_side is Side.BUY else -float(trade.qty)
            trade_history.append((now, signed_qty, float(trade.qty) * float(trade.price)))
            cutoff = now - 2000
            while trade_history and trade_history[0][0] < cutoff:
                trade_history.popleft()
            continue

        depth_event = event
        book.apply_update(depth_event)
        bids = book.get_depth("bid", levels=5)
        asks = book.get_depth("ask", levels=5)
        if not bids or not asks:
            continue

        current_bid = bids[0]
        current_ask = asks[0]
        if previous_bid is None or previous_ask is None:
            ofi = 0.0
        else:
            bid_p, bid_q = previous_bid
            ask_p, ask_q = previous_ask
            cur_bp, cur_bq = current_bid
            cur_ap, cur_aq = current_ask
            bid_component = cur_bq if cur_bp > bid_p else (-bid_q if cur_bp < bid_p else cur_bq - bid_q)
            ask_component = -cur_aq if cur_ap < ask_p else (ask_q if cur_ap > ask_p else -(cur_aq - ask_q))
            ofi = bid_component + ask_component

        previous_bid = current_bid
        previous_ask = current_ask
        ofi_history.append((now, ofi))
        mid_history.append((now, (current_bid[0] + current_ask[0]) / 2.0))
        cutoff = now - 2000
        while ofi_history and ofi_history[0][0] < cutoff:
            ofi_history.popleft()
        while mid_history and mid_history[0][0] < cutoff:
            mid_history.popleft()

        half = 0 if now <= session_midpoint else 1
        sample = _features_from_book(book, now, session, half, ofi_history, trade_history, mid_history)
        if sample is None:
            continue

        row = {feature: getattr(sample, feature) for feature in FEATURES}
        row.update({
            "timestamp_ms": sample.timestamp_ms,
            "session": session,
            "half": half,
            "mid": sample.mid,
        })
        for horizon in HORIZONS_MS:
            future = _future_mid(all_mid_times, all_mids, sample.timestamp_ms, horizon)
            if future is None:
                row[f"future_mid_{horizon}ms"] = float("nan")
                row[f"move_{horizon}ms"] = float("nan")
                row[f"direction_{horizon}ms"] = float("nan")
                continue
            threshold = max(TICK_SIZE, 0.5 * (sample.spread_bps / 10_000.0) * sample.mid)
            delta = future - sample.mid
            row[f"future_mid_{horizon}ms"] = future
            row[f"move_{horizon}ms"] = float(abs(delta) >= threshold)
            row[f"direction_{horizon}ms"] = 1.0 if delta > 0 else 0.0
        samples.append(row)

    return pd.DataFrame(samples)


def build_dataset(captures_root: Path, sessions: tuple[str, ...] = ("A", "B", "C", "D")) -> pd.DataFrame:
    frames = [extract_session(captures_root / session, session) for session in sessions]
    return pd.concat(frames, ignore_index=True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--captures-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    df = build_dataset(args.captures_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.output, index=False)
    print({"rows": len(df), "columns": len(df.columns), "sessions": sorted(df["session"].unique())})
