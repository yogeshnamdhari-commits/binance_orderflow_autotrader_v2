from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
import numpy as np

from app.v19.config import V19Config
from app.mm.backtest import MMResult


@dataclass(frozen=True)
class MMGateResult:
    passed: bool
    reasons: tuple[str, ...]
    total_pnl_bps: float
    realized_spread_bps: float
    adverse_selection_bps: float
    fill_count: int
    cancel_count: int
    inventory_max: float
    inventory_final: float
    regime_profitability: dict[int, float]
    cost_stress: dict[float, float]


def evaluate_mm_gate(
    mm_result: MMResult,
    config: V19Config,
    cost_stress_multipliers: Sequence[float] = (1.0, 1.25, 1.5, 2.0),
) -> MMGateResult:
    reasons: list[str] = []

    if mm_result.total_pnl_bps <= 0:
        reasons.append("Total PnL is not positive")
    if mm_result.realized_spread_bps <= 0:
        reasons.append("Realized spread capture is not positive")
    if mm_result.adverse_selection_bps > mm_result.realized_spread_bps * 0.5:
        reasons.append("Adverse selection exceeds 50% of realized spread")
    if mm_result.fill_count < 10:
        reasons.append("Insufficient fill count for statistical validity")
    if abs(mm_result.inventory_final) > 0.5:
        reasons.append("Final inventory exceeds risk threshold")
    if mm_result.inventory_max > 0.8:
        reasons.append("Maximum inventory exceeded risk threshold")

    regime_profits = list(mm_result.regime_profitability.values())
    if regime_profits and any(p <= 0 for p in regime_profits):
        reasons.append("At least one volatility regime is non-positive")

    cost_stress = {}
    for mult in cost_stress_multipliers:
        stressed_pnl = mm_result.total_pnl_bps / mult
        cost_stress[float(mult)] = float(stressed_pnl)
        if stressed_pnl <= 0:
            reasons.append(f"Cost stress {mult}x removes the economic edge")

    passed = len(reasons) == 0

    return MMGateResult(
        passed=passed,
        reasons=tuple(reasons),
        total_pnl_bps=float(mm_result.total_pnl_bps),
        realized_spread_bps=float(mm_result.realized_spread_bps),
        adverse_selection_bps=float(mm_result.adverse_selection_bps),
        fill_count=mm_result.fill_count,
        cancel_count=mm_result.cancel_count,
        inventory_max=float(mm_result.inventory_max),
        inventory_final=float(mm_result.inventory_final),
        regime_profitability=mm_result.regime_profitability,
        cost_stress=cost_stress,
    )
