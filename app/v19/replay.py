from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

from .config import V19Config
from .features import L2Event, compute_orderflow_features
from .pipeline import run_forward_pipeline
from .walk_forward import make_purged_splits
from .v16_control import aligned_v16_outcomes


class ReconstructionIntegrityError(Exception):
    """Raised when a reconstructed order book violates causal invariants."""

    def __init__(self, message: str, *, event_index: int | None = None, update_u: int | None = None, update_pu: int | None = None, previous_u: int | None = None, ts_ms: int | None = None, best_bid_before: float | None = None, best_ask_before: float | None = None, best_bid_after: float | None = None, best_ask_after: float | None = None, affected_levels: list[str] | None = None, snapshot_last_id: int | None = None):
        super().__init__(message)
        self.event_index = event_index
        self.update_u = update_u
        self.update_pu = update_pu
        self.previous_u = previous_u
        self.ts_ms = ts_ms
        self.best_bid_before = best_bid_before
        self.best_ask_before = best_ask_before
        self.best_bid_after = best_bid_after
        self.best_ask_after = best_ask_after
        self.affected_levels = affected_levels or []
        self.snapshot_last_id = snapshot_last_id


@dataclass
class _DepthUpdate:
    ts_ms: int
    U: int | None
    u: int | None
    pu: int | None
    b: list[tuple[float, float]]
    a: list[tuple[float, float]]
    raw_json: str


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
    return tuple(sorted(((float(p), float(q)) for p, q in value if float(q) > 0), key=lambda x: x[0]))


def _book_event(ts_ms: int, bids: dict[float, float], asks: dict[float, float]) -> L2Event | None:
    if not bids or not asks:
        return None
    bid_levels = tuple(sorted(bids.items(), key=lambda x: x[0], reverse=True))
    ask_levels = tuple(sorted(asks.items(), key=lambda x: x[0]))
    bid_px, bid_qty = bid_levels[0]
    ask_px, ask_qty = ask_levels[0]
    if ask_px < bid_px:
        raise ValueError(f"reconstructed order book crossed: best ask {ask_px} < best bid {bid_px}")
    return L2Event(
        ts_ms * 1_000_000,
        bid_px,
        bid_qty,
        ask_px,
        ask_qty,
        bid_levels=bid_levels,
        ask_levels=ask_levels,
    )


def _load_snapshot(snapshot_path: Path) -> tuple[dict[float, float], dict[float, float], int | None]:
    if not snapshot_path.exists():
        raise FileNotFoundError(snapshot_path)
    with snapshot_path.open("r", encoding="utf-8") as f:
        snap = json.load(f)
    bids = {float(p): float(q) for p, q in snap.get("bids", []) if float(q) > 0}
    asks = {float(p): float(q) for p, q in snap.get("asks", []) if float(q) > 0}
    if not bids or not asks:
        raise ValueError("snapshot must contain non-empty bid and ask levels")
    last_update_id = snap.get("lastUpdateId")
    return bids, asks, last_update_id


def _parse_v10_depth_update(raw_json: str, ts_ms: int) -> _DepthUpdate | None:
    payload = json.loads(raw_json)
    data = payload.get("data", payload)
    inner_type = str(data.get("e", "")).lower()
    if inner_type != "depthupdate":
        return None
    U = data.get("U")
    u = data.get("u")
    pu = data.get("pu")
    b = [(float(p), float(q)) for p, q in data.get("b", [])]
    a = [(float(p), float(q)) for p, q in data.get("a", [])]
    return _DepthUpdate(ts_ms=ts_ms, U=U, u=u, pu=pu, b=b, a=a, raw_json=raw_json)


def _apply_depth_update(
    bids: dict[float, float],
    asks: dict[float, float],
    update: _DepthUpdate,
) -> tuple[dict[float, float], dict[float, float], list[str]]:
    affected: list[str] = []
    for price, qty in update.b:
        if qty > 0:
            bids[price] = qty
            affected.append(f"b:{price}:{qty}")
        else:
            if price in bids:
                del bids[price]
                affected.append(f"b:{price}:REMOVE")
    for price, qty in update.a:
        if qty > 0:
            asks[price] = qty
            affected.append(f"a:{price}:{qty}")
        else:
            if price in asks:
                del asks[price]
                affected.append(f"a:{price}:REMOVE")
    return bids, asks, affected


def _reconstruct_depth(
    rows: Iterable[dict],
    snapshot_path: Path | None = None,
) -> list[L2Event]:
    """Reconstruct the full order book from snapshot + incremental depth updates.

    The reconstruction is sequence-driven: depth updates are ordered by their
    native Binance sequence identifier (u), not by event_time_ms.  Sequence
    continuity (pu == previous u) is validated before each update is applied.
    The book is updated incrementally; existing levels that are absent from a
    particular update are preserved.  If the reconstructed book ever crosses
    (best_bid >= best_ask), a ReconstructionIntegrityError is raised with full
    diagnostics.  No silent fallback to a full-snapshot replacement is permitted.
    """
    if snapshot_path is not None:
        bids, asks, snapshot_last_id = _load_snapshot(snapshot_path)
    else:
        bids, asks, snapshot_last_id = {}, {}, None

    updates: list[_DepthUpdate] = []
    for row in rows:
        raw_json = row.get("raw_json")
        if not raw_json:
            continue
        ts_ms = int(row.get("event_time_ms", row.get("ts_ms", row.get("timestamp_ms", row.get("time", 0)))))
        update = _parse_v10_depth_update(raw_json, ts_ms)
        if update is not None:
            updates.append(update)

    if not updates:
        raise ValueError("no depthUpdate events found in the event file")

    updates.sort(key=lambda u: u.u if u.u is not None else 0)

    events: list[L2Event] = []
    previous_u: int | None = None

    for idx, update in enumerate(updates):
        if idx == 0 and snapshot_last_id is not None and update.U is not None and update.u is not None:
            if not (update.U <= snapshot_last_id + 1 <= update.u):
                raise ReconstructionIntegrityError(
                    f"Snapshot bootstrap failure at update index {idx}: "
                    f"snapshot lastUpdateId={snapshot_last_id} not in first update range "
                    f"[U={update.U}, u={update.u}]. "
                    f"The snapshot and events stream are not aligned. "
                    f"Required: U <= lastUpdateId + 1 <= u.",
                    event_index=idx,
                    update_u=update.u,
                    update_pu=update.pu,
                    previous_u=previous_u,
                    ts_ms=update.ts_ms,
                    snapshot_last_id=snapshot_last_id,
                )

        if idx > 0:
            if update.pu is not None and previous_u is not None and update.pu != previous_u:
                raise ReconstructionIntegrityError(
                    f"Binance depth sequence gap at update index {idx}: "
                    f"pu={update.pu} != previous u={previous_u}",
                    event_index=idx,
                    update_u=update.u,
                    update_pu=update.pu,
                    previous_u=previous_u,
                    ts_ms=update.ts_ms,
                    snapshot_last_id=snapshot_last_id,
                )

        best_bid_before = max(bids.keys()) if bids else None
        best_ask_before = min(asks.keys()) if asks else None

        bids, asks, affected = _apply_depth_update(bids, asks, update)

        best_bid_after = max(bids.keys()) if bids else None
        best_ask_after = min(asks.keys()) if asks else None

        if best_bid_after is not None and best_ask_after is not None and best_ask_after < best_bid_after:
            raise ReconstructionIntegrityError(
                f"Reconstructed order book crossed at update index {idx} (ts_ms={update.ts_ms}, U={update.U}, u={update.u}, pu={update.pu}): "
                f"best_bid={best_bid_after}, best_ask={best_ask_after}",
                event_index=idx,
                update_u=update.u,
                update_pu=update.pu,
                previous_u=previous_u,
                ts_ms=update.ts_ms,
                best_bid_before=best_bid_before,
                best_ask_before=best_ask_before,
                best_bid_after=best_bid_after,
                best_ask_after=best_ask_after,
                affected_levels=affected,
                snapshot_last_id=snapshot_last_id,
            )

        previous_u = update.u

        event = _book_event(update.ts_ms, bids, asks)
        if event is not None:
            events.append(event)

    if len(events) < 3:
        raise ValueError("historical replay requires at least three valid depth states")
    return events


def _trade_rows(rows: Iterable[dict]) -> list[tuple[int, float, float, str]]:
    trades: list[tuple[int, float, float, str]] = []
    for row in rows:
        event_type = str(row.get("event_type", row.get("type", ""))).lower()
        if event_type != "trade":
            continue
        ts_ms = int(row.get("event_time_ms", row.get("ts_ms", row.get("timestamp_ms", row.get("time", 0)))))
        raw_json = row.get("raw_json")
        if raw_json is None:
            continue
        payload = json.loads(raw_json)
        data = payload.get("data", payload)
        price = float(data.get("p", row.get("price", 0.0)))
        qty = float(data.get("q", row.get("qty", row.get("quantity", 0.0))))
        buyer_is_maker = bool(data.get("m", row.get("buyer_is_maker", False)))
        side = "SELL" if buyer_is_maker else "BUY"
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


def prepare_l2_dataset(
    events_path: Path,
    horizon_ns: int,
    snapshot_path: Path | None = None,
    config: V19Config | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    if horizon_ns <= 0:
        raise ValueError("horizon_ns must be positive")
    if config is None:
        from .config import V19Config
        config = V19Config(
            symbol="BTCUSDT",
            prediction_horizon_ms=500,
            feature_names=("queue_imbalance_1_zscore", "queue_imbalance_3_zscore", "ofi_1_zscore", "ofi_3_zscore", "signed_trade_flow_zscore", "spread_bps_zscore", "depth_concentration", "queue_change_intensity_zscore", "liquidity_state_zscore", "volatility_regime"),
            min_train_events=5000,
            min_test_events=1000,
            embargo_events=50,
            max_feature_age_ms=500,
            maker_round_trip_cost_bps=1.5,
            taker_round_trip_cost_bps=3.0,
            non_fill_opportunity_cost_bps=0.5,
            maker_share=0.75,
            cost_stress_multipliers=(1.0, 1.25, 1.5, 2.0),
            live_order_submission=False,
            config_hash="",
        )
    rows = _load_rows(events_path)
    if snapshot_path is None:
        snapshot_path = events_path.parent / "snapshot.json"
    books = _reconstruct_depth(rows, snapshot_path=snapshot_path)
    trades = _trade_rows(rows)
    observed_events = _attach_trades(books, trades)
    timestamps: list[int] = []
    X: list[list[float]] = []
    returns: list[float] = []
    fills: list[int] = []
    book_ts = np.asarray([x.timestamp_ns for x in books], dtype=np.int64)
    feature_names = list(config.feature_names)
    for event in books:
        target_ns = event.timestamp_ns + horizon_ns
        future_idx = int(np.searchsorted(book_ts, target_ns, side="left"))
        if future_idx >= len(books):
            break
        future = books[future_idx]
        features = compute_orderflow_features(observed_events, event.timestamp_ns)
        mid = (event.bid_px + event.ask_px) / 2.0
        future_mid = (future.bid_px + future.ask_px) / 2.0
        side = "BUY" if features["ofi_1_zscore"] >= 0 else "SELL"
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
    snapshot_path = events_path.parent / "snapshot.json"
    X, returns, fills, timestamps = prepare_l2_dataset(events_path, config.prediction_horizon_ms * 1_000_000, snapshot_path=snapshot_path, config=config)
    if v16_outcomes is None:
        splits = make_purged_splits(timestamps, config.min_train_events, config.min_test_events, config.embargo_events)
        test_timestamps = np.asarray([timestamps[i] for split in splits for i in split.test], dtype=np.int64)
        v16_outcomes = aligned_v16_outcomes(events_path.parent, test_timestamps, max_feature_age_ms=config.max_feature_age_ms)
    return run_forward_pipeline(X, returns, fills, timestamps, config, v16_outcomes)
