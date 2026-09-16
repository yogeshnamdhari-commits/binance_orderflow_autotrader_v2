from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
import numpy as np

from app.v19.config import V19Config
from app.mm.backtest import MMBacktestResult
from app.mm.regime_validator import RegimeResult


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
    mm_result: MMBacktestResult,
    config: V19Config,
    cost_stress_multipliers: Sequence[float] = (1.0, 1.25, 1.5, 2.0),
) -> MMGateResult:
    reasons: list[str] = []

    if mm_result.pnl_bps <= 0:
        reasons.append("Total PnL is not positive")
    if mm_result.avg_realized_pnl_per_fill_bps <= 0 and mm_result.fills > 0:
        reasons.append("Realized spread capture is not positive")
    if mm_result.avg_adverse_selection_bps > 0 and mm_result.fills > 0:
        if mm_result.avg_adverse_selection_bps > abs(mm_result.avg_realized_pnl_per_fill_bps) * 0.5:
            reasons.append("Adverse selection exceeds 50% of realized spread")
    if mm_result.fills < 10:
        reasons.append("Insufficient fill count for statistical validity")
    if abs(mm_result.inventory_final) > 0.5:
        reasons.append("Final inventory exceeds risk threshold")
    if mm_result.inventory_max > 0.8:
        reasons.append("Maximum inventory exceeded risk threshold")

    regime_profits = [rr.pnl_bps for rr in mm_result.regime_results.values() if isinstance(rr, RegimeResult)]
    if regime_profits and any(p <= 0 for p in regime_profits):
        reasons.append("At least one volatility regime is non-positive")

    cost_stress = {}
    for mult in cost_stress_multipliers:
        stressed_pnl = mm_result.pnl_bps / mult
        cost_stress[float(mult)] = float(stressed_pnl)
        if stressed_pnl <= 0:
            reasons.append(f"Cost stress {mult}x removes the economic edge")

    passed = len(reasons) == 0

    regime_profitability = {}
    for regime_id, rr in mm_result.regime_results.items():
        if isinstance(rr, RegimeResult):
            regime_profitability[regime_id] = rr.pnl_bps

    return MMGateResult(
        passed=passed,
        reasons=tuple(reasons),
        total_pnl_bps=float(mm_result.pnl_bps),
        realized_spread_bps=float(mm_result.avg_realized_pnl_per_fill_bps * mm_result.fills) if mm_result.fills > 0 else 0.0,
        adverse_selection_bps=float(mm_result.avg_adverse_selection_bps),
        fill_count=mm_result.fills,
        cancel_count=mm_result.cancels,
        inventory_max=float(mm_result.inventory_max),
        inventory_final=float(mm_result.inventory_final),
        regime_profitability=regime_profitability,
        cost_stress=cost_stress,
    )
