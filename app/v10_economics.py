"""Transparent passive-order expected-value accounting for V10."""
from __future__ import annotations


def passive_order_ev_bps(
    fill_probability: float,
    spread_capture_bps: float,
    fee_rebate_bps: float,
    adverse_selection_bps: float,
    inventory_cost_bps: float,
    exit_cost_bps: float,
    cancellation_cost_bps: float,
) -> float:
    p = float(fill_probability)
    if not 0 <= p <= 1:
        raise ValueError("fill_probability must be in [0,1]")
    terms = [spread_capture_bps, fee_rebate_bps, adverse_selection_bps, inventory_cost_bps, exit_cost_bps, cancellation_cost_bps]
    if not all(__import__("math").isfinite(float(x)) for x in terms):
        raise ValueError("economic terms must be finite")
    gross_if_filled = float(spread_capture_bps) + float(fee_rebate_bps) - float(adverse_selection_bps) - float(inventory_cost_bps) - float(exit_cost_bps)
    return p * gross_if_filled - float(cancellation_cost_bps)
