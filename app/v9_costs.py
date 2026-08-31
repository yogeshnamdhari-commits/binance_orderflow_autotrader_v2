"""Measured-cost economic gate for V9 research.

No default fee/spread/slippage assumptions are supplied. A calibrated cost
record must explicitly provide every required component.
"""
from __future__ import annotations

REQUIRED = ("fee_bps", "spread_bps", "slippage_bps", "funding_bps")


def net_expectancy(gross_bps: float, costs: dict[str, float]) -> float:
    missing = [k for k in REQUIRED if k not in costs]
    if missing:
        raise ValueError(f"missing measured cost components: {missing}")
    values = {k: float(costs[k]) for k in REQUIRED}
    if any(v < 0 for v in values.values()):
        raise ValueError("cost components cannot be negative")
    gross = float(gross_bps)
    return gross - sum(values.values())
