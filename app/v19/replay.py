from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import numpy as np

from .config import V19Config
from .features import L2Event, compute_orderflow_features
from .pipeline import run_forward_pipeline
from .walk_forward import make_purged_splits
from .v16_control import aligned_v16_outcomes


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


def _book_event(ts_ms: int, bids: dict[float, float], asks: dict[float, float]) -> L2Event | None:
    bid_levels = tuple(sorted(((p, q) for p, q in bids.items() if q > 0), key=lambda x: x[0], reverse=True))
    ask_levels = tuple(sorted(((p, q) for p, q in asks.items() if q > 0), key=lambda x: x[0]))
    if not bid_levels or not ask_levels:
        return None
    bid_px, bid_qty = bid_levels[0]
    ask_px, ask_qty = ask_levels[0]
    if ask_px < bid_px:
        raise ValueError("reconstructed order book crossed: ask price below bid price")
    return L2Event(
        ts_ms * 1_000_000,
        bid_px,
        bid_qty,
        ask_px,
        ask_qty,
        bid_levels=bid_levels,
        ask_levels=ask_levels,
    )


def _reconstruct_depth(rows: Iterable[dict]) -> list[L2Event]:
    bids: dict[float, float] = {}
    asks: dict[float, float] = {}
    initialized = False
    snapshot_ts: int | None = None
    events: list[L2Event] = []

    for row in sorted(rows, key=lambda r: int(r.get("ts_ms", r.get("timestamp_ms", r.get("time", 0))))):
        if str(row.get("type", "")).lower() != "depth":
            continue
        ts_ms = int(row.get("ts_ms", row.get("timestamp_ms", row.get("time", 0))))
        raw_bids = row.get("bids_json", row.get("bids"))
        raw_asks = row.get("asks_json", row.get("asks"))
        if raw_bids is not None or raw_asks is not None:
            next_bids = dict(_levels(raw_bids))
            next_asks = dict(_levels(raw_asks))
            if next_bids and next_asks:
                bids, asks, initialized = next_bids, next_asks, True
                event = _book_event(ts_ms, bids, asks)
                if event is not None:
                    events.append(event)
            continue

        update_type = str(row.get("update_type", "")).lower()
        side = str(row.get("side", "")).lower()
        if side not in {"b", "a", "bid", "ask"}:
            raise ValueError(f"invalid Binance depth side: {side!r}")
        price = float(row["price"])
        qty = float(row.get("qty", row.get("quantity", 0.0)))
        book = bids if side in {"b", "bid"} else asks
        if update_type == "snap":
            if snapshot_ts != ts_ms:
                bids.clear()
                asks.clear()
                snapshot_ts = ts_ms
            book[price] = qty
            initialized = True
        elif update_type == "set":
            if not initialized:
                raise ValueError("Binance T_DEPTH set update arrived before an order-book snapshot")
            if qty <= 0:
                book.pop(price, None)
            else:
                book[price] = qty
        elif update_type == "delta":
            if not initialized:
                raise ValueError("Binance T_DEPTH delta update arrived before an order-book snapshot")
            new_qty = book.get(price, 0.0) + qty
            if new_qty < -1e-12:
                raise ValueError("Binance T_DEPTH delta produced negative level quantity")
            if new_qty <= 1e-12:
                book.pop(price, None)
            else:
                book[price] = new_qty
        else:
            raise ValueError(f"unsupported Binance depth update_type: {update_type!r}")
        event = _book_event(ts_ms, bids, asks)
        if event is not None:
            events.append(event)

    if len(events) < 3:
        raise ValueError("historical replay requires at least three valid depth states")
    return events


def _trade_rows(rows: Iterable[dict]) -> list[tuple[int, float, float, str]]:
    trades: list[tuple[int, float, float, str]] = []
    for row in rows:
        if str(row.get("type", "")).lower() != "trade":
            continue
        ts_ms = int(row.get("ts_ms", row.get("timestamp_ms", row.get("time", 0))))
        price = float(row["price"])
        qty = float(row.get("qty", row.get("quantity", 0.0)))
        side = "SELL" if str(row.get("buyer_is_maker", "false")).lower() == "true" else "BUY"
        trades.append((ts_ms * 1_000_000, price, qty, side))
    return sorted(trades, key=lambda x: x[0])


def _attach_trades(books: list[L2Event], trades: list[tuple[int, float, float, str]]) -> list[L2Event]:
    if not trades:
        return books
    combined: list[L2Event] = list(books)
    book_ts = np.asarray([e.timestamp_ns for e in books], dtype=np.int64)
    for ts_ns, _, qty, side in trades:
        idx = int(np.searchsorted(book_ts, ts_ns, side="right") - 1)
        if idx < 0:
            continue
        state = books[idx]
        combined.append(L2Event(
            ts_ns, state.bid_px, state.bid_qty, state.ask_px, state.ask_qty,
            trade_side=side, trade_qty=qty,
            bid_levels=state.bid_levels, ask_levels=state.ask_levels,
        ))
    return sorted(combined, key=lambda e: (e.timestamp_ns, 0 if e.trade_qty == 0 else 1))


def prepare_l2_dataset(events_path: Path, horizon_ns: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    if horizon_ns <= 0:
        raise ValueError("horizon_ns must be positive")
    rows = _load_rows(events_path)
    books = _reconstruct_depth(rows)
    trades = _trade_rows(rows)
    observed_events = _attach_trades(books, trades)
    timestamps: list[int] = []
    X: list[list[float]] = []
    returns: list[float] = []
    fills: list[int] = []
    book_ts = np.asarray([x.timestamp_ns for x in books], dtype=np.int64)
    feature_names = (
        "queue_imbalance_1", "queue_imbalance_3", "ofi_1", "ofi_3",
        "signed_trade_flow", "spread_bps", "depth_concentration",
        "queue_change_intensity", "liquidity_state",
    )
    for event in books:
        target_ns = event.timestamp_ns + horizon_ns
        future_idx = int(np.searchsorted(book_ts, target_ns, side="left"))
        if future_idx >= len(books):
            break
        future = books[future_idx]
        features = compute_orderflow_features(observed_events, event.timestamp_ns)
        mid = (event.bid_px + event.ask_px) / 2.0
        future_mid = (future.bid_px + future.ask_px) / 2.0
        side = "BUY" if features["ofi_1"] >= 0 else "SELL"
        if side == "BUY":
            filled = any(t >= event.timestamp_ns and t <= target_ns and s == "SELL" and p <= event.bid_px for t, p, _, s in trades)
        else:
            filled = any(t >= event.timestamp_ns and t <= target_ns and s == "BUY" and p >= event.ask_px for t, p, _, s in trades)
        timestamps.append(event.timestamp_ns)
        X.append([features[name] for name in feature_names])
        returns.append((future_mid / mid - 1.0) * 10_000.0 * (1.0 if side == "BUY" else -1.0))
        fills.append(int(filled))
    return np.asarray(X), np.asarray(returns), np.asarray(fills), np.asarray(timestamps)


def run_historical_replay(events_path: Path, config: V19Config, v16_outcomes: np.ndarray | None = None) -> dict[str, object]:
    if config.live_order_submission:
        raise ValueError("historical replay requires live submission to remain disabled")
    X, returns, fills, timestamps = prepare_l2_dataset(events_path, config.prediction_horizon_ms * 1_000_000)
    if v16_outcomes is None:
        splits = make_purged_splits(timestamps, config.min_train_events, config.min_test_events, config.embargo_events)
        test_timestamps = np.asarray([timestamps[i] for split in splits for i in split.test], dtype=np.int64)
        v16_outcomes = aligned_v16_outcomes(events_path.parent, test_timestamps, max_feature_age_ms=config.max_feature_age_ms)
    return run_forward_pipeline(X, returns, fills, timestamps, config, v16_outcomes)
