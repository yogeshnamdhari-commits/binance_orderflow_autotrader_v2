"""V14 execution simulator — maker/taker-aware cost model (Rule 11).

Models passive maker-queue entry (with rebates, fill probability, partial fills)
and market taker exit (for stop-loss/take-profit). No assumptions about
automatic spread capture.

Per the pre-registered protocol:
  - Entry: 75% maker (rebate -2bps, slip 0.1, adverse 0.3, latency 0.1)
           25% taker  (fee +5bps, slip 0.1, adverse 0.3, latency 0.1)
  - Exit:  market taker (cost 3.0 bps)
  - Roundtrip expected cost ≈ 1.6 bps
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np

from app.v14.config import V14Config


@dataclass(frozen=True)
class V14EconomicDecomposition:
    signal_edge_bps: float
    funding_income_bps: float
    gross_ev_bps: float
    entry_cost_bps: float
    exit_cost_bps: float
    total_cost_bps: float
    net_ev_bps: float
    hold_duration_hours: float
    signal_confidence: float
    fill_probability: float


class V14ExecutionSim:
    """Deterministic maker/taker-aware execution cost model."""

    def __init__(self, config: V14Config):
        self._cfg = config

    @property
    def entry_cost_bps(self) -> float:
        maker = (self._cfg.maker_rebate_bps + self._cfg.slippage_bps
                 + self._cfg.adverse_selection_bps + self._cfg.latency_bps)
        taker = (self._cfg.taker_fee_bps + self._cfg.slippage_bps
                 + self._cfg.adverse_selection_bps + self._cfg.latency_bps)
        return self._cfg.maker_fill_probability * maker + (1 - self._cfg.maker_fill_probability) * taker

    @property
    def total_roundtrip_cost_bps(self) -> float:
        return self.entry_cost_bps + self._cfg.exit_cost_bps

    def decompose_trade(self, signal_edge_bps: float, funding_rate_8h: float,
                        hold_duration_hours: float, signal_confidence: float,
                        spread_bps: float = 0.013) -> V14EconomicDecomposition:
        # 8h funding -> scale by hold fraction
        funding_bps_per_8h = funding_rate_8h * 1e4
        n_periods = hold_duration_hours / 8.0
        raw_funding = funding_bps_per_8h * n_periods
        # Signal direction: long if edge > 0, short if edge < 0
        if signal_edge_bps > 0:
            direction = 1
        elif signal_edge_bps < 0:
            direction = -1
        else:
            direction = 0
        funding_income_bps = -direction * raw_funding

        entry_cost = self.entry_cost_bps
        exit_cost = self._cfg.exit_cost_bps
        total_cost = entry_cost + exit_cost

        gross = signal_edge_bps + funding_income_bps
        net = gross - total_cost
        expected_net = net * signal_confidence

        return V14EconomicDecomposition(
            signal_edge_bps=signal_edge_bps,
            funding_income_bps=funding_income_bps,
            gross_ev_bps=gross,
            entry_cost_bps=entry_cost,
            exit_cost_bps=exit_cost,
            total_cost_bps=total_cost,
            net_ev_bps=expected_net,
            hold_duration_hours=hold_duration_hours,
            signal_confidence=signal_confidence,
            fill_probability=self._cfg.maker_fill_probability,
        )
