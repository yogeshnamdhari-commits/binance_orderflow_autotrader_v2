"""Empirical adapter: converts captured Binance events into V10 execution observations.

This module reads a validated V10 capture session, replays the book
deterministically, simulates passive orders at each decision point, and
produces a DataFrame of execution observations suitable for the existing
v10_execution_research pipeline.

No live order placement. No parameter tuning on evaluation data.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.v10_book_replay import V10BookReplay, ReplayStatus
from app.v10_market_data import normalize_ws_event
from app.v10_passive_sim import PassiveOrder, apply_trade
from app.v10_queue import QueueEstimator


@dataclass(frozen=True)
class _MidSnapshot:
    timestamp: pd.Timestamp
    mid: float
    best_bid: float
    best_ask: float
    bid_depth: float
    ask_depth: float


def load_session_events(session_dir: str | Path) -> list[dict[str, Any]]:
    """Load and parse all events from a V10 capture session directory."""
    session_dir = Path(session_dir)
    events_path = session_dir / "events.jsonl"
    if not events_path.is_file():
        raise FileNotFoundError(f"events.jsonl not found in {session_dir}")

    events: list[dict[str, Any]] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("parse_error"):
            continue
        raw_json = row.get("raw_json")
        if not raw_json:
            continue
        try:
            event = normalize_ws_event(raw_json, receive_ns=row.get("receive_ns", 0))
        except Exception:
            continue
        events.append({
            "stream": event.stream,
            "event_type": event.event_type,
            "event_time_ms": event.event_time_ms,
            "receive_ns": event.receive_time_ns,
            "payload": event.payload,
            "raw_json": event.raw_json,
        })
    return events


def replay_book(events: list[dict[str, Any]]) -> tuple[ReplayStatus, dict[Decimal, Decimal], dict[Decimal, Decimal], int | None]:
    """Replay the full event stream through the deterministic book replayer.

    Returns the final replay status, bid/ask books, and last update id.
    """
    replay = V10BookReplay()

    snapshot = {
        "lastUpdateId": 0,
        "bids": [["65000.0", "1.0"]],
        "asks": [["65000.1", "1.0"]],
    }

    depth_events: list[dict[str, Any]] = []
    first_depth = True

    for event in events:
        if event["event_type"] == "depthUpdate":
            data = event["payload"].get("data", event["payload"])
            if first_depth:
                try:
                    snapshot_id = int(data.get("U", 0)) - 1
                except (TypeError, ValueError):
                    snapshot_id = 0
                snapshot = {"lastUpdateId": snapshot_id, "bids": [["65000.0", "1.0"]], "asks": [["65000.1", "1.0"]]}
                first_depth = False
            depth_events.append(data)

    result = replay.replay(snapshot, depth_events)
    return result.status, result.bids, result.asks, result.last_update_id


def extract_mid_prices(events: list[dict[str, Any]]) -> list[_MidSnapshot]:
    """Extract mid-price snapshots from bookTicker and depthUpdate events."""
    snapshots: list[_MidSnapshot] = []
    best_bid: float | None = None
    best_ask: float | None = None
    bid_depth = 0.0
    ask_depth = 0.0

    for event in events:
        ts = pd.Timestamp(event["receive_ns"], unit="ns", tz="UTC") if event["receive_ns"] else pd.Timestamp.now(tz="UTC")

        if event["event_type"] == "bookTicker":
            data = event["payload"].get("data", event["payload"])
            try:
                best_bid = float(data["b"])
                best_ask = float(data["a"])
                bid_depth = float(data.get("B", 0))
                ask_depth = float(data.get("A", 0))
            except (KeyError, TypeError, ValueError):
                continue

        elif event["event_type"] == "depthUpdate":
            data = event["payload"].get("data", event["payload"])
            b_updates = data.get("b", [])
            a_updates = data.get("a", [])
            if b_updates:
                try:
                    best_bid = float(b_updates[0][0])
                    bid_depth = sum(float(u[1]) for u in b_updates if float(u[1]) > 0)
                except (IndexError, TypeError, ValueError):
                    pass
            if a_updates:
                try:
                    best_ask = float(a_updates[0][0])
                    ask_depth = sum(float(u[1]) for u in a_updates if float(u[1]) > 0)
                except (IndexError, TypeError, ValueError):
                    pass

        if best_bid is not None and best_ask is not None and best_bid > 0 and best_ask > 0:
            mid = (best_bid + best_ask) / 2.0
            snapshots.append(_MidSnapshot(
                timestamp=ts,
                mid=mid,
                best_bid=best_bid,
                best_ask=best_ask,
                bid_depth=bid_depth,
                ask_depth=ask_depth,
            ))

    return snapshots


def simulate_passive_orders(
    events: list[dict[str, Any]],
    *,
    order_quantity: float = 0.01,
    decision_every_n: int = 10,
    horizon_ms: int = 1000,
    queue_ahead_fraction: float = 0.1,
) -> pd.DataFrame:
    """Simulate passive orders at regular intervals through the event stream.

    For each decision point, places a hypothetical passive order at the best
    bid and best ask, then tracks fill outcomes through subsequent trades.

    ``queue_ahead_fraction`` determines what fraction of the displayed depth is
    treated as queue-ahead. In real markets, an order at the best bid/ask joins
    behind only the volume already at that price level, not the entire depth.

    Returns a DataFrame with columns:
    - timestamp, side, fill_fraction, queue_ahead, time_to_fill_ms,
      filled, mid_at_placement, post_mid, adverse_selection_bps
    """
    snapshots = extract_mid_prices(events)
    if not snapshots:
        return pd.DataFrame(columns=[
            "timestamp", "side", "fill_fraction", "queue_ahead",
            "time_to_fill_ms", "filled", "mid_at_placement", "post_mid",
            "adverse_selection_bps",
        ])

    mid_df = pd.DataFrame([{
        "timestamp": s.timestamp,
        "mid": s.mid,
        "best_bid": s.best_bid,
        "best_ask": s.best_ask,
        "bid_depth": s.bid_depth,
        "ask_depth": s.ask_depth,
    } for s in snapshots])

    mid_df["timestamp"] = pd.to_datetime(mid_df["timestamp"], utc=True)
    mid_df = mid_df.sort_values("timestamp").reset_index(drop=True)

    trade_events: list[dict[str, Any]] = []
    for event in events:
        if event["event_type"] == "trade":
            data = event["payload"].get("data", event["payload"])
            try:
                trade_events.append({
                    "timestamp": pd.Timestamp(event["receive_ns"], unit="ns", tz="UTC") if event["receive_ns"] else pd.Timestamp.now(tz="UTC"),
                    "price": float(data["p"]),
                    "qty": float(data["q"]),
                    "buyer_is_maker": bool(data.get("m", False)),
                })
            except (KeyError, TypeError, ValueError):
                continue

    trade_df = pd.DataFrame(trade_events)
    if not trade_df.empty:
        trade_df["timestamp"] = pd.to_datetime(trade_df["timestamp"], utc=True)
        trade_df = trade_df.sort_values("timestamp").reset_index(drop=True)

    observations: list[dict[str, Any]] = []
    queue_est = QueueEstimator()

    decision_indices = list(range(0, len(mid_df), decision_every_n))

    for idx in decision_indices:
        row = mid_df.iloc[idx]
        ts = row["timestamp"]
        mid = row["mid"]
        best_bid = row["best_bid"]
        best_ask = row["best_ask"]

        future_mid = mid_df[mid_df["timestamp"] > ts]
        if future_mid.empty:
            continue
        post_row = future_mid.iloc[min(int(horizon_ms / 100), len(future_mid) - 1)]
        post_mid = post_row["mid"]

        future_trades = trade_df[trade_df["timestamp"] > ts] if not trade_df.empty else pd.DataFrame()

        for side, price, displayed_size in [
            ("bid", best_bid, row["bid_depth"]),
            ("ask", best_ask, row["ask_depth"]),
        ]:
            if price <= 0 or displayed_size <= 0:
                continue

            qty = min(order_quantity, displayed_size)
            ahead = queue_est.start(side, displayed_size * queue_ahead_fraction)

            order = PassiveOrder(
                side=side,
                price=Decimal(str(price)),
                quantity=Decimal(str(qty)),
                queue_ahead=Decimal(str(ahead)),
            )

            fill_time_ms: float | None = None
            remaining_trades = future_trades

            for _, trade_row in remaining_trades.iterrows():
                trade_price = Decimal(str(trade_row["price"]))
                trade_qty = Decimal(str(trade_row["qty"]))
                buyer_is_maker = trade_row["buyer_is_maker"]

                before_fill = order.filled
                order = apply_trade(order, trade_price, trade_qty, buyer_is_maker)

                if order.filled > before_fill and fill_time_ms is None:
                    dt = (trade_row["timestamp"] - ts).total_seconds() * 1000.0
                    fill_time_ms = max(0.0, dt)

            fill_fraction = float(order.filled / order.quantity) if order.quantity > 0 else 0.0
            filled = 1 if fill_fraction > 0 else 0
            time_to_fill_ms = fill_time_ms if fill_time_ms is not None else float(horizon_ms)

            if side == "ask":
                signed_return = (post_mid / mid - 1.0) * 1.0
            else:
                signed_return = (post_mid / mid - 1.0) * -1.0
            adverse_selection_bps = signed_return * 10_000.0

            observations.append({
                "timestamp": ts,
                "side": side,
                "fill_fraction": fill_fraction,
                "queue_ahead": float(ahead),
                "time_to_fill_ms": time_to_fill_ms,
                "filled": filled,
                "mid_at_placement": mid,
                "post_mid": post_mid,
                "adverse_selection_bps": adverse_selection_bps,
            })

    if not observations:
        return pd.DataFrame(columns=[
            "timestamp", "side", "fill_fraction", "queue_ahead",
            "time_to_fill_ms", "filled", "mid_at_placement", "post_mid",
            "adverse_selection_bps",
        ])

    result = pd.DataFrame(observations)
    result["timestamp"] = pd.to_datetime(result["timestamp"], utc=True)
    result = result.sort_values("timestamp").reset_index(drop=True)
    return result


def empirical_integration(
    session_dir: str | Path,
    *,
    order_quantity: float = 0.01,
    decision_every_n: int = 10,
    horizon_ms: int = 1000,
) -> dict[str, Any]:
    """Full empirical integration pipeline for a captured session.

    Returns a dict with:
    - replay_status: book replay status
    - n_events: total events processed
    - n_observations: execution observations produced
    - observations: the DataFrame of observations
    - summary: execution economics summary
    """
    events = load_session_events(session_dir)
    if not events:
        raise ValueError(f"no valid events found in {session_dir}")

    replay_status, bids, asks, last_update_id = replay_book(events)
    observations = simulate_passive_orders(
        events,
        order_quantity=order_quantity,
        decision_every_n=decision_every_n,
        horizon_ms=horizon_ms,
    )

    from app.v10_execution_research import summarize_execution_economics

    summary: dict[str, Any] = {}
    if not observations.empty:
        try:
            summary = summarize_execution_economics(observations[[
                "fill_fraction", "adverse_selection_bps", "queue_ahead",
            ]])
        except ValueError:
            summary = {"orders": 0, "filled_orders": 0, "fill_rate": 0.0}

    return {
        "replay_status": replay_status.value if hasattr(replay_status, "value") else str(replay_status),
        "n_events": len(events),
        "n_observations": len(observations),
        "last_update_id": last_update_id,
        "observations": observations,
        "summary": summary,
    }
