from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import numpy as np

from .config import V19Config
from .features import L2Event, compute_orderflow_features
from .pipeline import run_forward_pipeline


def _load_rows(events_path: Path) -> list[dict]:
    if not events_path.exists():
        raise FileNotFoundError(events_path)
    rows: list[dict] = []
    with events_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if not rows:
        raise ValueError("historical L2 event file is empty")
    return rows


def _levels(raw: str | list | None) -> tuple[tuple[float, float], ...]:
    if raw is None:
        return ()
    value = json.loads(raw) if isinstance(raw, str) else raw
    return tuple((float(p), float(q)) for p, q in value)


def prepare_l2_dataset(events_path: Path, horizon_ns: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Create causal features and future labels from authentic L2/trade rows.

    Only rows at or before each decision timestamp enter the feature calculation.
    Forward mid-price return and fill outcomes are deliberately computed from
    later observations and are never passed back into the feature layer.
    """
    rows = _load_rows(events_path)
    books: list[L2Event] = []
    trades: list[tuple[int, float, float, str]] = []
    for row in rows:
        kind = str(row.get("type", "")).lower()
        ts_ms = int(row.get("ts_ms", row.get("timestamp_ms", 0)))
        if kind == "depth":
            bids = _levels(row.get("bids_json", row.get("bids")))
            asks = _levels(row.get("asks_json", row.get("asks")))
            if bids and asks:
                books.append(L2Event(ts_ms * 1_000_000, bids[0][0], bids[0][1], asks[0][0], asks[0][1], bid_levels=bids, ask_levels=asks))
        elif kind == "trade":
            side = "SELL" if str(row.get("buyer_is_maker", "false")).lower() == "true" else "BUY"
            trades.append((ts_ms * 1_000_000, float(row["price"]), float(row["qty"]), side))
    books.sort(key=lambda x: x.timestamp_ns)
    trades.sort(key=lambda x: x[0])
    if len(books) < 3:
        raise ValueError("historical replay requires at least three valid depth events")

    timestamps: list[int] = []
    X: list[list[float]] = []
    returns: list[float] = []
    fills: list[int] = []
    for i, event in enumerate(books):
        target_ns = event.timestamp_ns + horizon_ns
        future = next((x for x in books[i + 1:] if x.timestamp_ns >= target_ns), None)
        if future is None:
            break
        features = compute_orderflow_features(books[: i + 1], event.timestamp_ns)
        mid = (event.bid_px + event.ask_px) / 2.0
        future_mid = (future.bid_px + future.ask_px) / 2.0
        side = "BUY" if features["ofi_1"] >= 0 else "SELL"
        if side == "BUY":
            filled = any(t >= event.timestamp_ns and t <= target_ns and s == "SELL" and p <= event.bid_px for t, p, _, s in trades)
        else:
            filled = any(t >= event.timestamp_ns and t <= target_ns and s == "BUY" and p >= event.ask_px for t, p, _, s in trades)
        timestamps.append(event.timestamp_ns)
        X.append([features[name] for name in (
            "queue_imbalance_1", "queue_imbalance_3", "ofi_1", "ofi_3",
            "signed_trade_flow", "spread_bps", "depth_concentration",
            "queue_change_intensity", "liquidity_state",
        )])
        returns.append((future_mid / mid - 1.0) * 10_000.0 * (1.0 if side == "BUY" else -1.0))
        fills.append(int(filled))
    return np.asarray(X), np.asarray(returns), np.asarray(fills), np.asarray(timestamps)


def run_historical_replay(events_path: Path, config: V19Config) -> dict[str, object]:
    if config.live_order_submission:
        raise ValueError("historical replay requires live submission to remain disabled")
    X, returns, fills, timestamps = prepare_l2_dataset(events_path, config.prediction_horizon_ms * 1_000_000)
    return run_forward_pipeline(X, returns, fills, timestamps, config)
