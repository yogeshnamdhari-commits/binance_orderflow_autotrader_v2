from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Sequence
import numpy as np

FEATURE_NAMES = (
    "queue_imbalance_1_zscore",
    "queue_imbalance_3_zscore",
    "ofi_1_zscore",
    "ofi_3_zscore",
    "signed_trade_flow_zscore",
    "spread_bps_zscore",
    "depth_concentration",
    "queue_change_intensity_zscore",
    "liquidity_state_zscore",
    "volatility_regime",
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


def _zscore_normalize(values: list[float], window: int = 100) -> float:
    if len(values) < 2:
        return 0.0
    recent = values[-window:] if len(values) >= window else values
    arr = np.array(recent, dtype=float)
    mean = np.mean(arr)
    std = np.std(arr)
    if std < 1e-10:
        return 0.0
    return float((arr[-1] - mean) / std)


def _volatility_regime(spreads: list[float], window: int = 100) -> float:
    if len(spreads) < 20:
        return 1.0
    recent = spreads[-window:] if len(spreads) >= window else spreads
    arr = np.array(recent, dtype=float)
    p20 = np.percentile(arr, 20)
    p80 = np.percentile(arr, 80)
    current = arr[-1]
    if current <= p20:
        return 0.0
    elif current >= p80:
        return 2.0
    else:
        return 1.0


def compute_orderflow_features(
    events: Sequence[L2Event],
    now_ns: int,
    levels: int = 3,
    window_ns: int = 2_000_000_000,
) -> dict[str, float]:
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

    imbalance_1_hist = [_imbalance(e, 1) for e in recent]
    imbalance_3_hist = [_imbalance(e, 3) for e in recent]
    ofi_1_hist = [_ofi(recent[i-1] if i > 0 else None, e, 1) for i, e in enumerate(recent)]
    ofi_3_hist = [_ofi(recent[i-1] if i > 0 else None, e, 3) for i, e in enumerate(recent)]

    signed_volume = sum(
        e.trade_qty if e.trade_side.upper() == "BUY" else -e.trade_qty
        for e in recent
        if e.trade_qty > 0 and e.trade_side.upper() in {"BUY", "SELL"}
    )
    signed_vol_hist = [
        sum(
            e2.trade_qty if e2.trade_side.upper() == "BUY" else -e2.trade_qty
            for e2 in recent[:i+1]
            if e2.trade_qty > 0 and e2.trade_side.upper() in {"BUY", "SELL"}
        )
        for i in range(len(recent))
    ]

    spread_bps = 10_000.0 * (current.ask_px - current.bid_px) / ((current.ask_px + current.bid_px) / 2.0)
    spread_hist = [
        10_000.0 * (e.ask_px - e.bid_px) / ((e.ask_px + e.bid_px) / 2.0)
        for e in recent
    ]

    total_depth = sum(q for _, q in _depth(current, "bid", levels)) + sum(q for _, q in _depth(current, "ask", levels))
    top_depth = current.bid_qty + current.ask_qty
    depth_concentration = top_depth / total_depth if total_depth else 0.0

    queue_change = abs(_ofi(previous, current, 3))
    queue_change_hist = [abs(_ofi(recent[i-1] if i > 0 else None, e, 3)) for i, e in enumerate(recent)]
    queue_change_intensity = float(queue_change / max(len(recent), 1))

    liquidity_state = total_depth / max(current.ask_px - current.bid_px, current.ask_px * 1e-8)
    liquidity_hist = [
        (sum(q for _, q in _depth(e, "bid", levels)) + sum(q for _, q in _depth(e, "ask", levels)))
        / max(e.ask_px - e.bid_px, e.ask_px * 1e-8)
        for e in recent
    ]

    out = {
        "queue_imbalance_1_zscore": _zscore_normalize(imbalance_1_hist),
        "queue_imbalance_3_zscore": _zscore_normalize(imbalance_3_hist),
        "ofi_1_zscore": _zscore_normalize(ofi_1_hist),
        "ofi_3_zscore": _zscore_normalize(ofi_3_hist),
        "signed_trade_flow_zscore": _zscore_normalize(signed_vol_hist),
        "spread_bps_zscore": _zscore_normalize(spread_hist),
        "depth_concentration": float(depth_concentration),
        "queue_change_intensity_zscore": _zscore_normalize(queue_change_hist),
        "liquidity_state_zscore": _zscore_normalize(liquidity_hist),
        "volatility_regime": _volatility_regime(spread_hist),
    }

    if not all(isfinite(x) for x in out.values()):
        raise ValueError("feature calculation produced a non-finite value")

    return out
