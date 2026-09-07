"""V12 execution model — realistic Binance BTCUSDT futures execution costs.

Includes funding rate income as a revenue stream (per Rule 13).
Does NOT assume guaranteed fills, guaranteed spread capture, zero slippage,
zero adverse selection, or instantaneous execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .config import V12Config, V12EconomicDecomposition


@dataclass(frozen=True)
class V12ExecutionConfig:
    """Frozen execution configuration."""
    taker_fee_bps: float = 5.0
    maker_fee_bps: float = 2.0
    slippage_bps: float = 0.5
    adverse_selection_bps: float = 0.5
    latency_bps: float = 0.1
    exit_cost_bps: float = 5.0  # Round-trip: re-enter to close
    stop_loss_bps: float = 50.0
    take_profit_bps: float = 50.0
    holding_hours: float = 8.0  # Minimum one funding period


EXIT_COST_BPS = 5.0  # round-trip re-entry cost: taker + slippage + adverse + latency


class V12ExecutionModel:
    """Realistic execution model with funding awareness.

    Economic decomposition per trade (Rule 10):
        EXPECTED GROSS RETURN - SPREAD - FEES - SLIPPAGE - ADVERSE
        - LATENCY - MARKET IMPACT = EXPECTED NET RETURN
    """

    def __init__(self, config: V12Config | V12ExecutionConfig | None = None):
        if config is None:
            self._cfg = V12ExecutionConfig()
            self._base_cfg = V12Config()
        elif isinstance(config, V12ExecutionConfig):
            self._cfg = config
            self._base_cfg = V12Config()
        else:
            self._base_cfg = config
            self._cfg = V12ExecutionConfig(
                taker_fee_bps=config.taker_fee_bps,
                maker_fee_bps=config.maker_fee_bps,
                slippage_bps=config.slippage_bps,
                adverse_selection_bps=config.adverse_selection_bps,
                latency_bps=config.latency_bps,
                exit_cost_bps=EXIT_COST_BPS,
                stop_loss_bps=config.stop_loss_bps,
                take_profit_bps=config.take_profit_bps,
                holding_hours=config.max_holding_hours,
            )
        self.total_entry_cost = (
            self._cfg.taker_fee_bps
            + self._cfg.slippage_bps
            + self._cfg.adverse_selection_bps
            + self._cfg.latency_bps
        )
        self.total_exit_cost = (
            self._cfg.taker_fee_bps
            + self._cfg.slippage_bps
            + self._cfg.adverse_selection_bps
            + self._cfg.latency_bps
        )
        self.total_roundtrip_cost = self.total_entry_cost + self.total_exit_cost

    def decompose_trade(
        self,
        signal_edge_bps: float,
        funding_rate_8h: float,
        hold_duration_hours: float,
        signal_confidence: float,
        spread_bps: float = 0.013,
    ) -> V12EconomicDecomposition:
        """Full economic decomposition of a trade.

        Args:
            signal_edge_bps: Predicted return from order-flow signal
            funding_rate_8h: Binance 8-hour funding rate as a fraction
                (e.g. 0.0001 = +0.01% per 8h). Per Binance convention, a
                POSITIVE rate means LONGS pay SHORTS. Positive signal_edge
                implies a long position (long pays); negative implies short
                (short receives).
            hold_duration_hours: Expected holding period
            signal_confidence: Model probability of correct direction (0-1)
            spread_bps: Market spread at execution

        Returns:
            Complete economic decomposition
        """
        funding_bps_per_8h = funding_rate_8h * 1e4
        n_funding_periods = hold_duration_hours / 8.0
        # Binance: positive rate => longs pay, shorts receive.
        # signal_edge > 0 => long (direction +1); < 0 => short (direction -1).
        if signal_edge_bps > 0:
            direction = 1
        elif signal_edge_bps < 0:
            direction = -1
        else:
            direction = 0
        funding_income_bps = -direction * funding_bps_per_8h * n_funding_periods

        # Total costs
        spread_paid = spread_bps  # Taker pays the spread
        costs = [
            self.total_entry_cost,
            self.total_exit_cost,
            spread_paid,
        ]
        total_cost = sum(costs)

        # Gross = signal edge + funding income
        gross = signal_edge_bps + funding_income_bps

        # Net = gross - costs
        net = gross - total_cost

        # Adjusted by confidence (probability of being correct)
        expected_net = net * signal_confidence

        return V12EconomicDecomposition(
            signal_edge_bps=signal_edge_bps,
            funding_income_bps=funding_income_bps,
            spread_paid_bps=spread_paid,
            taker_fee_bps=self._cfg.taker_fee_bps,
            slippage_bps=self._cfg.slippage_bps,
            adverse_selection_bps=self._cfg.adverse_selection_bps,
            exit_cost_bps=self._cfg.exit_cost_bps,
            gross_ev_bps=gross,
            total_cost_bps=total_cost,
            net_ev_bps=expected_net,
            hold_duration_hours=hold_duration_hours,
            signal_confidence=signal_confidence,
        )

    def breakeven_funding_bps(self, signal_edge_bps: float, confidence: float, hold_duration_hours: float = 8.0) -> float:
        """Required 8-hour funding rate (bps) to break even given a signal edge."""
        if confidence <= 0:
            return float("inf")
        total_cost = self.total_roundtrip_cost + 0.013  # + spread
        required_funding = (total_cost - signal_edge_bps) / confidence
        n_periods = hold_duration_hours / 8.0
        return required_funding / n_periods if n_periods > 0 else float("inf")

    def cost_components(self) -> dict[str, float]:
        return {
            "taker_fee_bps": self._cfg.taker_fee_bps,
            "slippage_bps": self._cfg.slippage_bps,
            "adverse_selection_bps": self._cfg.adverse_selection_bps,
            "latency_bps": self._cfg.latency_bps,
            "exit_cost_bps": self._cfg.exit_cost_bps,
            "spread_bps": 0.013,
            "total_roundtrip_cost_bps": self.total_roundtrip_cost,
        }
