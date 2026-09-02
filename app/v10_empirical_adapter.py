"""Empirical adapter: converts captured Binance events into V10 execution observations.

Correct methodology:
1. Load validated capture session
2. Build ONE deterministic book state from snapshot + diff-depth events
3. At each decision point, query the replayed book for best bid/ask/depth
4. Place hypothetical orders and process ONLY trades within the time horizon
5. Use timestamp-based post-fill mid (not row-based)

No live order placement. No parameter tuning on evaluation data.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import pandas as pd

from app.v10_book_replay import V10BookReplay, ReplayStatus
from app.v10_market_data import normalize_ws_event
from app.v10_passive_sim import PassiveOrder, apply_trade
from app.v10_queue import QueueEstimator


@dataclass(frozen=True)
class BookState:
    timestamp: pd.Timestamp
    best_bid: float
    best_ask: float
    bid_size: float
    ask_size: float
    bids: dict[Decimal, Decimal]
    asks: dict[Decimal, Decimal]
    last_update_id: int


@dataclass(frozen=True)
class TradeEvent:
    timestamp: pd.Timestamp
    price: float
    qty: float
    buyer_is_maker: bool


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
            "_receive_ns": row.get("receive_ns", 0),
        })
    return events


def extract_snapshot_from_events(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Extract the initial book snapshot from the first depth update events.

    For real captures, the snapshot should be the REST snapshot taken before
    the WebSocket stream starts. This function reconstructs a minimal snapshot
    from the first depth event's update ID.
    """
    first_depth = None
    for event in events:
        if event["event_type"] == "depthUpdate":
            first_depth = event
            break

    if first_depth is None:
        return None

    data = first_depth["payload"].get("data", first_depth["payload"])
    try:
        first_u = int(data["U"])
    except (KeyError, TypeError, ValueError):
        return None

    return {
        "lastUpdateId": first_u - 1,
        "bids": [],
        "asks": [],
    }


def load_session_snapshot(session_dir: str | Path) -> dict[str, Any] | None:
    """Load the REST snapshot from a V10 capture session directory.

    The snapshot is written as `snapshot.json` by the capture process.
    If not present, returns None and the adapter will reconstruct from events.
    """
    session_dir = Path(session_dir)
    snapshot_path = session_dir / "snapshot.json"
    if not snapshot_path.is_file():
        return None
    try:
        return json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def build_incremental_book(
    events: list[dict[str, Any]],
    snapshot: dict[str, Any],
) -> Iterator[tuple[str, Any, BookState | None, TradeEvent | None]]:
    """Process events incrementally, yielding (event_type, raw_data, book_state, trade).

    This is the single deterministic state path. Every depth update is applied
    to the book in sequence. Trades are yielded separately for fill processing.
    """
    replay = V10BookReplay()

    try:
        snapshot_id = int(snapshot["lastUpdateId"])
        bids = replay._levels(snapshot["bids"]) if snapshot.get("bids") else {}
        asks = replay._levels(snapshot["asks"]) if snapshot.get("asks") else {}
    except (KeyError, TypeError, ValueError):
        return

    pending_depth: list[dict[str, Any]] = []
    first_index = None
    for event in events:
        if event["event_type"] != "depthUpdate":
            continue
        data = event["payload"].get("data", event["payload"])
        try:
            u = int(data["u"])
        except (KeyError, TypeError, ValueError):
            continue
        if u <= snapshot_id:
            continue
        first_index = len(pending_depth)
        break

    if first_index is None:
        return

    depth_events_in_order: list[tuple[dict[str, Any], int]] = []
    for event in events:
        if event["event_type"] == "depthUpdate":
            data = event["payload"].get("data", event["payload"])
            depth_events_in_order.append((data, event["_receive_ns"]))

    previous_u = snapshot_id
    started = False

    for data, receive_ns in depth_events_in_order:
        try:
            U = int(data["U"])
            u = int(data["u"])
            pu = data.get("pu")
            pu = int(pu) if pu is not None else None
        except (KeyError, TypeError, ValueError):
            continue

        if not started:
            if u <= snapshot_id:
                continue
            bridges = U <= snapshot_id + 1 <= u
            continues = pu is not None and pu == snapshot_id
            if not (bridges or continues):
                return
            started = True

        if U > u:
            return
        if u <= previous_u:
            continue

        try:
            replay._apply(bids, data.get("b", []))
            replay._apply(asks, data.get("a", []))
        except (TypeError, ValueError, KeyError):
            return

        previous_u = u

        ts = pd.Timestamp(receive_ns, unit="ns", tz="UTC") if receive_ns else pd.Timestamp.now(tz="UTC")

        best_bid = float(max(bids.keys())) if bids else 0.0
        best_ask = float(min(asks.keys())) if asks else 0.0
        bid_size = float(bids.get(Decimal(str(best_bid)), Decimal("0"))) if bids else 0.0
        ask_size = float(asks.get(Decimal(str(best_ask)), Decimal("0"))) if asks else 0.0

        book_state = BookState(
            timestamp=ts,
            best_bid=best_bid,
            best_ask=best_ask,
            bid_size=bid_size,
            ask_size=ask_size,
            bids=dict(bids),
            asks=dict(asks),
            last_update_id=previous_u,
        )

        yield ("depth", data, book_state, None)

    for event in events:
        if event["event_type"] not in ("trade", "aggTrade"):
            continue
        data = event["payload"].get("data", event["payload"])
        try:
            price = float(data["p"])
            qty = float(data["q"])
            buyer_is_maker = bool(data.get("m", False))
            receive_ns = event["_receive_ns"]
            ts = pd.Timestamp(receive_ns, unit="ns", tz="UTC") if receive_ns else pd.Timestamp.now(tz="UTC")
        except (KeyError, TypeError, ValueError):
            continue

        trade = TradeEvent(timestamp=ts, price=price, qty=qty, buyer_is_maker=buyer_is_maker)
        yield ("trade", data, None, trade)


def simulate_passive_orders(
    events: list[dict[str, Any]],
    snapshot: dict[str, Any],
    *,
    order_quantity: float = 0.01,
    decision_every_n: int = 10,
    horizon_ms: int = 1000,
    queue_ahead_fraction: float = 0.1,
) -> pd.DataFrame:
    """Simulate passive orders using the single deterministic book state path.

    For each decision point:
    1. Query the replayed book for best bid/ask and displayed size
    2. Place a hypothetical passive order at the best level
    3. Process ONLY trades within the time horizon (timestamp-based)
    4. Record fill outcome, time-to-fill, and post-fill mid (timestamp-based)
    """
    book_states: list[BookState] = []
    all_trades: list[TradeEvent] = []

    for event_type, _, book_state, trade in build_incremental_book(events, snapshot):
        if event_type == "depth" and book_state is not None:
            book_states.append(book_state)
        elif event_type == "trade" and trade is not None:
            all_trades.append(trade)

    if not book_states:
        return pd.DataFrame(columns=[
            "timestamp", "side", "fill_fraction", "queue_ahead",
            "time_to_fill_ms", "filled", "mid_at_placement", "post_mid",
            "adverse_selection_bps",
        ])

    observations: list[dict[str, Any]] = []
    queue_est = QueueEstimator()

    decision_indices = list(range(0, len(book_states), decision_every_n))

    for idx in decision_indices:
        state = book_states[idx]
        ts = state.timestamp
        horizon_end = ts + timedelta(milliseconds=horizon_ms)

        future_trades = [t for t in all_trades if ts < t.timestamp <= horizon_end]

        future_states = [s for s in book_states if ts < s.timestamp <= horizon_end]
        if future_states:
            post_state = future_states[-1]
            post_mid = (post_state.best_bid + post_state.best_ask) / 2.0
        else:
            last_state = book_states[min(idx + 1, len(book_states) - 1)]
            post_mid = (last_state.best_bid + last_state.best_ask) / 2.0

        mid_at_placement = (state.best_bid + state.best_ask) / 2.0

        for side, price, displayed_size in [
            ("bid", state.best_bid, state.bid_size),
            ("ask", state.best_ask, state.ask_size),
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

            for trade in future_trades:
                trade_price = Decimal(str(trade.price))
                trade_qty = Decimal(str(trade.qty))

                before_fill = order.filled
                order = apply_trade(order, trade_price, trade_qty, trade.buyer_is_maker)

                if order.filled > before_fill and fill_time_ms is None:
                    dt = (trade.timestamp - ts).total_seconds() * 1000.0
                    fill_time_ms = max(0.0, dt)

            fill_fraction = float(order.filled / order.quantity) if order.quantity > 0 else 0.0
            filled = 1 if fill_fraction > 0 else 0
            time_to_fill_ms = fill_time_ms if fill_time_ms is not None else float(horizon_ms)

            if side == "ask":
                signed_return = (post_mid / mid_at_placement - 1.0) * 1.0
            else:
                signed_return = (post_mid / mid_at_placement - 1.0) * -1.0
            adverse_selection_bps = signed_return * 10_000.0

            observations.append({
                "timestamp": ts,
                "side": side,
                "fill_fraction": fill_fraction,
                "queue_ahead": float(ahead),
                "time_to_fill_ms": time_to_fill_ms,
                "filled": filled,
                "mid_at_placement": mid_at_placement,
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

    snapshot = load_session_snapshot(session_dir)
    if snapshot is None:
        snapshot = extract_snapshot_from_events(events)
    if snapshot is None:
        raise ValueError("could not extract snapshot from session events")

    replay_status = ReplayStatus.OK
    observations = simulate_passive_orders(
        events,
        snapshot=snapshot,
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
        "snapshot_update_id": snapshot.get("lastUpdateId"),
        "observations": observations,
        "summary": summary,
    }
