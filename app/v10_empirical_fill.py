"""Research-only empirical passive-fill observation and summary utilities.

This module does not place orders and does not infer exchange FIFO position.
It converts replay outputs into auditable observations and summarizes realized
fill behavior. Queue position remains an explicit input to the upstream
simulator.
"""
from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

import pandas as pd


def _decimal(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value))


def _require_finite(value: float, name: str) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")


def build_fill_observation(
    *,
    order_id: str,
    signal_time_ns: int,
    order_time_ns: int,
    side: str,
    quoted_price: Decimal,
    quantity: Decimal,
    queue_ahead: Decimal,
    filled: Decimal,
    first_fill_time_ns: int | None,
    mid_at_order: Decimal,
    mid_after_fill: Decimal,
    forward_mid: Decimal,
) -> dict[str, Any]:
    """Create one normalized passive-order replay observation.

    Adverse selection is measured on the post-fill move against the passive
    position using ``mid_after_fill`` versus ``forward_mid``. Positive values
    therefore indicate an adverse move for the strategy.
    """
    if side not in {"bid", "ask"}:
        raise ValueError("side must be bid or ask")
    if signal_time_ns < 0 or order_time_ns < signal_time_ns:
        raise ValueError("invalid observation timestamps")
    if quoted_price <= 0 or quantity <= 0 or queue_ahead < 0 or filled < 0 or filled > quantity:
        raise ValueError("invalid order quantities or price")
    if mid_at_order <= 0 or mid_after_fill <= 0 or forward_mid <= 0:
        raise ValueError("mid prices must be positive")
    if first_fill_time_ns is not None and first_fill_time_ns < order_time_ns:
        raise ValueError("first fill cannot precede order time")

    fill_fraction = float(filled / quantity)
    time_to_first_fill_ns = None if first_fill_time_ns is None else int(first_fill_time_ns - order_time_ns)
    post_fill_return_bps = float((_decimal(forward_mid) / _decimal(mid_after_fill) - Decimal("1")) * Decimal("10000"))
    adverse_selection_bps = -post_fill_return_bps if side == "bid" else post_fill_return_bps

    return {
        "order_id": order_id,
        "signal_time_ns": int(signal_time_ns),
        "order_time_ns": int(order_time_ns),
        "side": side,
        "quoted_price": float(quoted_price),
        "quantity": float(quantity),
        "queue_ahead": float(queue_ahead),
        "filled": float(filled),
        "fill_fraction": fill_fraction,
        "filled_order": int(filled > 0),
        "fully_filled": int(filled == quantity),
        "first_fill_time_ns": None if first_fill_time_ns is None else int(first_fill_time_ns),
        "time_to_first_fill_ns": time_to_first_fill_ns,
        "mid_at_order": float(mid_at_order),
        "mid_after_fill": float(mid_after_fill),
        "forward_mid": float(forward_mid),
        "adverse_selection_bps": adverse_selection_bps,
    }


def empirical_fill_summary(observations: pd.DataFrame) -> dict[str, float | int]:
    """Summarize realized fill and economic observations without re-fitting data."""
    required = {"fill_fraction", "filled", "adverse_selection_bps", "net_ev_bps"}
    if not required.issubset(observations.columns):
        raise ValueError("missing required observation columns")
    if observations.empty:
        raise ValueError("observations must be non-empty")

    fill_fraction = observations["fill_fraction"].to_numpy(float)
    filled = observations["filled"].to_numpy(float)
    adverse = observations["adverse_selection_bps"].to_numpy(float)
    net_ev = observations["net_ev_bps"].to_numpy(float)
    for name, values in {
        "fill_fraction": fill_fraction,
        "filled": filled,
        "adverse_selection_bps": adverse,
        "net_ev_bps": net_ev,
    }.items():
        if not all(math.isfinite(float(v)) for v in values):
            raise ValueError(f"{name} must be finite")
    if ((fill_fraction < 0) | (fill_fraction > 1)).any():
        raise ValueError("fill_fraction must be in [0,1]")

    filled_orders = filled > 0
    partial_filled_orders = (filled > 0) & (fill_fraction < 1)
    return {
        "orders": int(len(observations)),
        "filled_orders": int(filled_orders.sum()),
        "fill_rate": float(filled_orders.mean()),
        "mean_fill_fraction": float(fill_fraction.mean()),
        "partial_fill_rate_among_filled": float(partial_filled_orders.sum() / filled_orders.sum()) if filled_orders.any() else 0.0,
        "mean_adverse_selection_bps": float(adverse[filled_orders].mean()) if filled_orders.any() else 0.0,
        "mean_net_ev_bps": float(net_ev.mean()),
    }
