"""V16 execution simulator — maker/taker with fill-probability model."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from app.v16.config import V16Config


@dataclass(frozen=True)
class V16ExecutionDecision:
    action: Literal["MAKER", "TAKER", "NONE"]
    predicted_return_bps: float
    fill_probability: float
    expected_pnl_bps: float
    entry_cost_bps: float
    exit_cost_bps: float
    total_cost_bps: float
    non_fill_cost_bps: float
    reason: str


class V16ExecutionSim:
    def __init__(self, config: V16Config):
        self._cfg = config

    def expected_pnl(self, predicted_return_bps: float, fill_prob: float,
                     maker: bool = True) -> float:
        cfg = self._cfg
        if maker:
            entry_cost = cfg.maker_entry_cost_bps
            non_fill_cost = cfg.non_fill_opportunity_cost_bps
        else:
            entry_cost = cfg.taker_entry_cost_bps
            non_fill_cost = 0.0
        exit_cost = cfg.exit_cost_bps
        total_cost = entry_cost + exit_cost + non_fill_cost
        expected_pnl = fill_prob * predicted_return_bps - total_cost
        return expected_pnl

    def route(self, predicted_return_bps: float, fill_prob: float) -> V16ExecutionDecision:
        cfg = self._cfg

        if predicted_return_bps <= 0:
            return V16ExecutionDecision(
                action="NONE", predicted_return_bps=predicted_return_bps,
                fill_probability=fill_prob, expected_pnl_bps=0.0,
                entry_cost_bps=0.0, exit_cost_bps=0.0,
                total_cost_bps=0.0, non_fill_cost_bps=0.0,
                reason="non_positive_predicted_return",
            )

        maker_pnl = self.expected_pnl(predicted_return_bps, fill_prob, maker=True)
        taker_pnl = self.expected_pnl(predicted_return_bps, 1.0, maker=False)

        if maker_pnl > taker_pnl and maker_pnl > 0:
            return V16ExecutionDecision(
                action="MAKER", predicted_return_bps=predicted_return_bps,
                fill_probability=fill_prob, expected_pnl_bps=maker_pnl,
                entry_cost_bps=cfg.maker_entry_cost_bps, exit_cost_bps=cfg.exit_cost_bps,
                total_cost_bps=cfg.maker_entry_cost_bps + cfg.exit_cost_bps,
                non_fill_cost_bps=cfg.non_fill_opportunity_cost_bps,
                reason="maker_optimal",
            )
        elif taker_pnl > 0:
            return V16ExecutionDecision(
                action="TAKER", predicted_return_bps=predicted_return_bps,
                fill_probability=1.0, expected_pnl_bps=taker_pnl,
                entry_cost_bps=cfg.taker_entry_cost_bps, exit_cost_bps=cfg.exit_cost_bps,
                total_cost_bps=cfg.taker_entry_cost_bps + cfg.exit_cost_bps,
                non_fill_cost_bps=0.0,
                reason="taker_optimal",
            )
        else:
            return V16ExecutionDecision(
                action="NONE", predicted_return_bps=predicted_return_bps,
                fill_probability=fill_prob, expected_pnl_bps=0.0,
                entry_cost_bps=0.0, exit_cost_bps=0.0,
                total_cost_bps=0.0, non_fill_cost_bps=0.0,
                reason="negative_expected_pnl",
            )
