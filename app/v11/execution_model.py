"""V11 execution cost model — realistic Binance BTCUSDT futures costs.

Does NOT assume:
- guaranteed passive fills
- guaranteed spread capture
- unrealistic maker rebates
- zero slippage
- zero adverse selection
- instantaneous execution
- favorable queue position without evidence
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class V11ExecutionConfig:
    """Frozen execution configuration — pre-registered with realistic Binance costs."""
    taker_fee_bps: float = 5.0        # Binance BTCUSDT taker fee (0.05%)
    maker_fee_bps: float = 2.0        # Binance BTCUSDT maker fee (0.02%)
    slippage_bps: float = 0.5         # Conservative slippage estimate
    adverse_selection_bps: float = 0.5  # Conservative adverse selection estimate
    latency_bps: float = 0.1          # Network + processing latency
    cancellation_cost_bps: float = 0.05
    inventory_cost_bps: float = 0.2
    exit_cost_bps: float = 0.3
    notional_usd: float = 10_000.0
    horizon_ms: int = 500


@dataclass(frozen=True)
class ExecutionResult:
    """Result of simulating orders under specific execution mode."""
    mode: str
    fill_probability: float
    revenue_bps: float
    fees_bps: float
    slippage_bps: float
    adverse_selection_bps: float
    net_ev_bps: float
    n_orders: int
    n_filled: int
    gross_ev_bps: float
    total_cost_bps: float


class V11ExecutionModel:
    """Realistic execution model for V11.

    Economic mechanism: Taker orders only when signal confidence exceeds
    dynamically calibrated breakeven threshold.
    """

    def __init__(self, config: V11ExecutionConfig):
        self._config = config
        self.total_cost_bps = (
            config.taker_fee_bps
            + config.slippage_bps
            + config.adverse_selection_bps
            + config.latency_bps
        )

    def simulate_taker(
        self,
        predicted_returns: pd.Series,
        fill_probabilities: pd.Series,
        spread_bps: float | None = None,
    ) -> ExecutionResult:
        """Simulate taker market order execution.

        Taker order:
        - Crosses spread to execute immediately
        - Pays taker fee
        - ~high fill probability (if size allows)
        - Slippage depends on market depth
        """
        if len(predicted_returns) == 0:
            return ExecutionResult(
                mode="taker", fill_probability=0.0, revenue_bps=0.0,
                fees_bps=0.0, slippage_bps=0.0, adverse_selection_bps=0.0,
                net_ev_bps=0.0, n_orders=0, n_filled=0,
                gross_ev_bps=0.0, total_cost_bps=0.0,
            )

        n_orders = len(predicted_returns)
        actual_spread = spread_bps if spread_bps is not None else 0.013  # measured BTCUSDT spread

        # Revenue: predicted return minus spread paid
        revenue = predicted_returns - actual_spread

        # Fees: taker fee per order (applied to filled orders only)
        filled = (fill_probabilities > 0.5).astype(int)  # conservative fill model
        n_filled = int(filled.sum())
        fill_prob = filled.mean()

        fees = self._config.taker_fee_bps * fill_prob
        slippage = self._config.slippage_bps * fill_prob
        adverse = self._config.adverse_selection_bps * fill_prob

        gross_ev = (fill_prob * revenue).mean()
        total_cost = fees + slippage + adverse + self._config.latency_bps * fill_prob
        net_ev = gross_ev - total_cost

        return ExecutionResult(
            mode="taker",
            fill_probability=float(fill_prob),
            revenue_bps=float(revenue.mean()),
            fees_bps=float(fees),
            slippage_bps=float(slippage),
            adverse_selection_bps=float(adverse),
            net_ev_bps=float(net_ev),
            n_orders=n_orders,
            n_filled=n_filled,
            gross_ev_bps=float(gross_ev),
            total_cost_bps=float(total_cost),
        )

    def breakeven_return_bps(self, fill_probability: float) -> float:
        """Compute required predicted return to break even at given fill probability."""
        return (
            self._config.taker_fee_bps
            + self._config.slippage_bps
            + self._config.adverse_selection_bps
            + self._config.latency_bps
        ) / max(fill_probability, 0.01)

    def cost_components(self) -> dict[str, float]:
        """Return cost component breakdown."""
        return {
            "taker_fee_bps": self._config.taker_fee_bps,
            "slippage_bps": self._config.slippage_bps,
            "adverse_selection_bps": self._config.adverse_selection_bps,
            "latency_bps": self._config.latency_bps,
            "total_cost_bps": self.total_cost_bps,
        }
