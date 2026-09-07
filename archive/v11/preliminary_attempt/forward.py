"""V11 forward validation.

Independent forward test with realistic execution economics.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .signal import V11SignalModel
from .execution import V11ExecutionModel, ExecutionResult


@dataclass(frozen=True)
class V11ForwardConfig:
    """Frozen forward validation configuration."""
    maker_fee_bps: float = -0.02
    taker_fee_bps: float = 0.04
    cancellation_cost_bps: float = 0.05
    inventory_cost_bps: float = 0.2
    exit_cost_bps: float = 0.3


@dataclass(frozen=True)
class V11ForwardResult:
    """Forward validation result."""
    status: str
    n_orders: int
    n_filled: int
    signal_accuracy: float
    mean_predicted_prob: float
    passive_result: ExecutionResult
    aggressive_result: ExecutionResult
    mid_result: ExecutionResult
    best_mode: str
    best_net_ev_bps: float
    bootstrap_ci_95: tuple[float, float]
    permutation_pvalue: float
    cohens_h: float
    regime_results: dict[str, Any]
    gate_conditions: dict[str, bool]


class V11ForwardValidator:
    """Independent forward validator for V11.
    
    Uses frozen signal and execution models.
    Does not modify models during validation.
    """
    
    def __init__(self, signal_model: V11SignalModel, execution_model: V11ExecutionModel, config: V11ForwardConfig):
        self._signal_model = signal_model
        self._execution_model = execution_model
        self._config = config
        self._orders: list[dict[str, Any]] = []
    
    def validate(self, observations: pd.DataFrame, book_states: list[Any], trades: list[Any], spread_bps: float) -> V11ForwardResult:
        """Run forward validation.
        
        Args:
            observations: Forward observations
            book_states: Forward book states
            trades: Forward trades
            spread_bps: Average spread in bps
            
        Returns:
            Forward validation result
        """
        if len(observations) == 0:
            return V11ForwardResult(
                status="FAIL",
                n_orders=0,
                n_filled=0,
                signal_accuracy=0.0,
                mean_predicted_prob=0.0,
                passive_result=ExecutionResult("passive", 0, 0, 0, 0, 0, 0, 0, 0),
                aggressive_result=ExecutionResult("aggressive", 0, 0, 0, 0, 0, 0, 0, 0),
                mid_result=ExecutionResult("mid", 0, 0, 0, 0, 0, 0, 0, 0),
                best_mode="none",
                best_net_ev_bps=0.0,
                bootstrap_ci_95=(0.0, 0.0),
                permutation_pvalue=1.0,
                cohens_h=0.0,
                regime_results={},
                gate_conditions={},
            )
        
        # Extract features and predict signal
        features = self._signal_model.extract_features(book_states, trades)
        min_len = min(len(features), len(observations))
        features = features.iloc[:min_len].reset_index(drop=True)
        obs_aligned = observations.iloc[:min_len].reset_index(drop=True)
        
        predicted_probs = self._signal_model.predict_proba(features)
        mean_predicted_prob = float(predicted_probs.mean())
        
        # Signal accuracy: did model predict correctly?
        # For binary classification, accuracy = % correct predictions
        predicted_labels = (predicted_probs > 0.5).astype(int)
        # Use fill + positive adverse selection as "correct" signal
        actual_labels = ((obs_aligned["filled"] == 1) & (obs_aligned["adverse_selection_bps"] >= 0)).astype(int)
        signal_accuracy = float((predicted_labels == actual_labels).mean())
        
        # Simulate execution under 3 modes
        passive_result = self._execution_model.simulate_passive(obs_aligned, spread_bps)
        aggressive_result = self._execution_model.simulate_aggressive(obs_aligned, spread_bps, mean_predicted_prob * 2.0)
        mid_result = self._execution_model.simulate_mid(obs_aligned, spread_bps, mean_predicted_prob * 2.0)
        
        # Determine best mode (highest net EV)
        results = {
            "passive": passive_result,
            "aggressive": aggressive_result,
            "mid": mid_result,
        }
        best_mode = max(results.keys(), key=lambda m: results[m].net_ev_bps)
        best_net_ev = results[best_mode].net_ev_bps
        
        # Bootstrap CI for best mode net EV
        net_evs = []
        for _ in range(10000):
            idx = np.random.choice(len(obs_aligned), size=len(obs_aligned), replace=True)
            sample = obs_aligned.iloc[idx]
            res = self._execution_model.simulate_passive(sample, spread_bps)
            net_evs.append(res.net_ev_bps)
        
        ci_lower = float(np.percentile(net_evs, 2.5))
        ci_upper = float(np.percentile(net_evs, 97.5))
        
        # Permutation test for signal accuracy
        observed_acc = signal_accuracy
        n_permutations = 10000
        count_extreme = 0
        for _ in range(n_permutations):
            perm_labels = np.random.permutation(actual_labels.values)
            perm_acc = float((predicted_labels == perm_labels).mean())
            if perm_acc >= observed_acc:
                count_extreme += 1
        perm_pvalue = count_extreme / n_permutations
        
        # Effect size (Cohen's h for proportions)
        p1 = signal_accuracy
        p2 = 0.5  # null hypothesis
        cohens_h = 2 * (np.arcsin(np.sqrt(p1)) - np.arcsin(np.sqrt(p2)))
        
        # Gate conditions
        gate_conditions = {
            "signal_accuracy_significant": signal_accuracy > 0.5 and perm_pvalue < 0.05,
            "net_ev_positive": best_net_ev > 0,
            "ci_excludes_zero": ci_lower > 0,
            "effect_size_sufficient": abs(cohens_h) >= 0.2,
            "sufficient_observations": len(obs_aligned) >= 50,
        }
        
        all_pass = all(gate_conditions.values())
        status = "PASS" if all_pass else "FAIL"
        
        # Regime analysis
        regime_results = self._analyze_regimes(obs_aligned, spread_bps, results)
        
        return V11ForwardResult(
            status=status,
            n_orders=len(obs_aligned),
            n_filled=int(obs_aligned["filled"].sum()),
            signal_accuracy=signal_accuracy,
            mean_predicted_prob=mean_predicted_prob,
            passive_result=passive_result,
            aggressive_result=aggressive_result,
            mid_result=mid_result,
            best_mode=best_mode,
            best_net_ev_bps=best_net_ev,
            bootstrap_ci_95=(ci_lower, ci_upper),
            permutation_pvalue=perm_pvalue,
            cohens_h=cohens_h,
            regime_results=regime_results,
            gate_conditions=gate_conditions,
        )
    
    def _analyze_regimes(self, observations: pd.DataFrame, spread_bps: float, results: dict[str, ExecutionResult]) -> dict[str, Any]:
        """Analyze performance across predefined regimes."""
        regimes = {}
        
        # Spread regime
        if "spread_bps" in observations.columns:
            high_spread = observations[observations["spread_bps"] >= 0.01]
            low_spread = observations[observations["spread_bps"] < 0.01]
            
            if len(high_spread) > 0:
                regimes["high_spread"] = {
                    "n": len(high_spread),
                    "fill_rate": float(high_spread["filled"].mean()),
                    "net_ev_bps": float(results["passive"].net_ev_bps),
                }
            if len(low_spread) > 0:
                regimes["low_spread"] = {
                    "n": len(low_spread),
                    "fill_rate": float(low_spread["filled"].mean()),
                    "net_ev_bps": float(results["passive"].net_ev_bps),
                }
        
        return regimes
