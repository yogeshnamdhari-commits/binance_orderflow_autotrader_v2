"""V15 execution router — dynamic maker/taker selection based on predicted net edge.

Decision logic:
1. Predict return magnitude (bps) from GBR model
2. Apply regime filter (only trade in high-vol + high-liquidity + tight-spread)
3. Compare predicted return against execution costs:
   - pred_return > taker_cost + safety_margin → TAKE (market order)
   - pred_return > maker_cost + safety_margin → POST (maker limit order)
   - pred_return < all-in maker cost → NO TRADE
4. Track expected net edge, fill probability, and realized cost
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from app.v15.config import V15Config
from app.v15.regime import V15RegimeFilter


@dataclass(frozen=True)
class V15ExecutionDecision:
    action: Literal["MAKER", "TAKER", "NONE"]
    predicted_return_bps: float
    expected_net_edge_bps: float
    entry_cost_bps: float
    exit_cost_bps: float
    total_cost_bps: float
    safety_margin_bps: float
    fill_probability: float
    regime_passed: bool
    reason: str


class V15ExecutionRouter:
    def __init__(self, config: V15Config, regime_filter: V15RegimeFilter | None = None):
        self._cfg = config
        self._regime = regime_filter or V15RegimeFilter()

    def route(self, predicted_return_bps: float, regime_passed: bool) -> V15ExecutionDecision:
        maker_cost = self._cfg.maker_rebate_bps + self._cfg.slippage_bps + self._cfg.adverse_selection_bps + self._cfg.latency_bps
        taker_cost = self._cfg.taker_fee_bps + self._cfg.slippage_bps + self._cfg.adverse_selection_bps + self._cfg.latency_bps
        exit_cost = self._cfg.exit_cost_bps
        margin = self._cfg.safety_margin_bps

        if not regime_passed:
            return V15ExecutionDecision(
                action="NONE", predicted_return_bps=predicted_return_bps,
                expected_net_edge_bps=0.0, entry_cost_bps=0.0, exit_cost_bps=0.0,
                total_cost_bps=0.0, safety_margin_bps=margin,
                fill_probability=0.0, regime_passed=False,
                reason="regime_filter_failed",
            )

        # Taker: pred_return must exceed taker cost + safety margin
        if predicted_return_bps > taker_cost + exit_cost + margin:
            net = predicted_return_bps - taker_cost - exit_cost
            return V15ExecutionDecision(
                action="TAKER", predicted_return_bps=predicted_return_bps,
                expected_net_edge_bps=net, entry_cost_bps=taker_cost, exit_cost_bps=exit_cost,
                total_cost_bps=taker_cost + exit_cost, safety_margin_bps=margin,
                fill_probability=1.0, regime_passed=True,
                reason="taker_route",
            )

        # Maker: pred_return must exceed maker cost + safety margin
        if predicted_return_bps > maker_cost + exit_cost + margin:
            net = predicted_return_bps - maker_cost - exit_cost
            return V15ExecutionDecision(
                action="MAKER", predicted_return_bps=predicted_return_bps,
                expected_net_edge_bps=net, entry_cost_bps=maker_cost, exit_cost_bps=exit_cost,
                total_cost_bps=maker_cost + exit_cost, safety_margin_bps=margin,
                fill_probability=self._cfg.maker_fill_probability, regime_passed=True,
                reason="maker_route",
            )

        return V15ExecutionDecision(
            action="NONE", predicted_return_bps=predicted_return_bps,
            expected_net_edge_bps=0.0, entry_cost_bps=0.0, exit_cost_bps=0.0,
            total_cost_bps=0.0, safety_margin_bps=margin,
            fill_probability=0.0, regime_passed=True,
            reason="below_breakeven",
        )

    def expected_net_edge(self, predicted_return_bps: float, regime_passed: bool) -> float:
        decision = self.route(predicted_return_bps, regime_passed)
        if decision.action == "NONE":
            return 0.0
        return decision.expected_net_edge_bps * decision.fill_probability
