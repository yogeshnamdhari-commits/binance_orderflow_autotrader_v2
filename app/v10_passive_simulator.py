"""Transparent single-order passive execution economics for V10 replay."""
from __future__ import annotations
import math


def simulate_passive_order(
    fill_fraction: float,
    spread_capture_bps: float,
    fee_rebate_bps: float,
    adverse_selection_bps: float,
    inventory_cost_bps: float,
    exit_cost_bps: float,
    cancellation_cost_bps: float,
) -> dict[str, float]:
    values = [fill_fraction, spread_capture_bps, fee_rebate_bps, adverse_selection_bps,
              inventory_cost_bps, exit_cost_bps, cancellation_cost_bps]
    if not all(math.isfinite(float(x)) for x in values):
        raise ValueError("all inputs must be finite")
    f = float(fill_fraction)
    if not 0 <= f <= 1:
        raise ValueError("fill_fraction must be in [0,1]")
    gross_filled = float(spread_capture_bps) + float(fee_rebate_bps)
    net_filled = gross_filled - float(adverse_selection_bps) - float(inventory_cost_bps) - float(exit_cost_bps)
    net_ev = f * net_filled - float(cancellation_cost_bps)
    return {
        "filled_fraction": f,
        "gross_if_filled_bps": gross_filled,
        "net_if_filled_bps": net_filled,
        "net_ev_bps": net_ev,
    }
