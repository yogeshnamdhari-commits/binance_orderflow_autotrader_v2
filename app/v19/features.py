from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Sequence

FEATURE_NAMES = (
    "queue_imbalance_1", "queue_imbalance_3", "ofi_1", "ofi_3",
    "signed_trade_flow", "spread_bps", "depth_concentration",
    "queue_change_intensity", "liquidity_state",
)


@dataclass(frozen=True)
class L2Event:
    timestamp_ns: int
    bid_px: float
    bid_qty: float
    ask_px: float
    ask_qty: float
    trade_side: str = ""
    trade_qty: float = 0.0
    bid_levels: tuple[tuple[float, float], ...] = ()
    ask_levels: tuple[tuple[float, float], ...] = ()


def feature_names() -> tuple[str, ...]:
    return FEATURE_NAMES


def _validate_event(e: L2Event) -> None:
    if e.bid_px <= 0 or e.ask_px <= 0 or e.bid_qty < 0 or e.ask_qty < 0:
        raise ValueError("L2 prices must be positive and quantities non-negative")
    if e.ask_px < e.bid_px:
        raise ValueError("ask price cannot be below bid price")
    if e.trade_qty < 0:
        raise ValueError("trade quantity cannot be negative")


def _depth(e: L2Event, side: str, levels: int) -> list[tuple[float, float]]:
    raw = e.bid_levels if side == "bid" else e.ask_levels
    if raw:
        return list(raw[:levels])
    return [(e.bid_px, e.bid_qty)] if side == "bid" else [(e.ask_px, e.ask_qty)]


def _imbalance(e: L2Event, levels: int) -> float:
    bid = sum(q for _, q in _depth(e, "bid", levels))
    ask = sum(q for _, q in _depth(e, "ask", levels))
    total = bid + ask
    return (bid - ask) / total if total else 0.0


def _ofi(previous: L2Event | None, current: L2Event, levels: int) -> float:
    if previous is None:
        return 0.0
    bid_now = sum(q for _, q in _depth(current, "bid", levels))
    bid_prev = sum(q for _, q in _depth(previous, "bid", levels))
    ask_now = sum(q for _, q in _depth(current, "ask", levels))
    ask_prev = sum(q for _, q in _depth(previous, "ask", levels))
    return (bid_now - bid_prev) - (ask_now - ask_prev)


def compute_orderflow_features(
    events: Sequence[L2Event],
    now_ns: int,
    levels: int = 3,
    window_ns: int = 2_000_000_000,
) -> dict[str, float]:
    """Compute only information observable at or before now_ns."""
    if levels <= 0 or window_ns <= 0:
        raise ValueError("levels and window_ns must be positive")
    observed = [e for e in events if e.timestamp_ns <= now_ns]
    if not observed:
        raise ValueError("at least one observed event is required")
    observed = sorted(observed, key=lambda e: e.timestamp_ns)
    for e in observed:
        _validate_event(e)
    current = observed[-1]
    start = now_ns - window_ns
    recent = [e for e in observed if e.timestamp_ns >= start]
    previous = observed[-2] if len(observed) >= 2 else None

    signed_volume = sum(
        e.trade_qty if e.trade_side.upper() == "BUY" else -e.trade_qty
        for e in recent
        if e.trade_qty > 0 and e.trade_side.upper() in {"BUY", "SELL"}
    )
    ofi_1 = _ofi(previous, current, 1)
    ofi_3 = _ofi(previous, current, levels)
    spread_bps = 10_000.0 * (current.ask_px - current.bid_px) / ((current.ask_px + current.bid_px) / 2.0)
    total_depth = sum(q for _, q in _depth(current, "bid", levels)) + sum(q for _, q in _depth(current, "ask", levels))
    top_depth = current.bid_qty + current.ask_qty
    depth_concentration = top_depth / total_depth if total_depth else 0.0
    queue_change = abs(ofi_3)
    liquidity_state = total_depth / max(current.ask_px - current.bid_px, current.ask_px * 1e-8)

    out = {
        "queue_imbalance_1": _imbalance(current, 1),
        "queue_imbalance_3": _imbalance(current, levels),
        "ofi_1": float(ofi_1),
        "ofi_3": float(ofi_3),
        "signed_trade_flow": float(signed_volume),
        "spread_bps": float(spread_bps),
        "depth_concentration": float(depth_concentration),
        "queue_change_intensity": float(queue_change / max(len(recent), 1)),
        "liquidity_state": float(liquidity_state),
    }
    if not all(isfinite(x) for x in out.values()):
        raise ValueError("feature calculation produced a non-finite value")
    return out
