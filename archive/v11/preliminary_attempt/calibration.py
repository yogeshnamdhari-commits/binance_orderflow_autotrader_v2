"""V11 calibration pipeline.

Separates calibration data from forward data.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .signal import V11SignalModel, V11SignalConfig
from .execution import V11ExecutionModel, V11ExecutionConfig


@dataclass(frozen=True)
class V11CalibrationConfig:
    """Frozen calibration configuration."""
    feature_window_ms: int = 1000
    prediction_horizon_ms: int = 1000
    min_spread_bps: float = 0.001
    regularization_c: float = 1.0
    class_weight: str = "balanced"
    maker_fee_bps: float = -0.02
    taker_fee_bps: float = 0.04
    cancellation_cost_bps: float = 0.05
    inventory_cost_bps: float = 0.2
    exit_cost_bps: float = 0.3
    order_quantity: float = 0.01
    horizon_ms: int = 1000


class V11Calibrator:
    """Calibrates V11 signal and execution models.
    
    Strictly separates calibration data from forward data.
    """
    
    def __init__(self, config: V11CalibrationConfig):
        self._config = config
        self._signal_config = V11SignalConfig(
            feature_window_ms=config.feature_window_ms,
            prediction_horizon_ms=config.prediction_horizon_ms,
            min_spread_bps=config.min_spread_bps,
            regularization_c=config.regularization_c,
            class_weight=config.class_weight,
        )
        self._execution_config = V11ExecutionConfig(
            maker_fee_bps=config.maker_fee_bps,
            taker_fee_bps=config.taker_fee_bps,
            cancellation_cost_bps=config.cancellation_cost_bps,
            inventory_cost_bps=config.inventory_cost_bps,
            exit_cost_bps=config.exit_cost_bps,
            order_quantity=config.order_quantity,
            horizon_ms=config.horizon_ms,
        )
        self._signal_model = V11SignalModel(self._signal_config)
        self._execution_model = V11ExecutionModel(self._execution_config)
        self._calibration_summary: dict[str, Any] = {}
    
    def calibrate(self, observations: pd.DataFrame, book_states: list[Any], trades: list[Any]) -> dict[str, Any]:
        """Calibrate signal model on training data.
        
        Args:
            observations: Calibration observations
            book_states: Book state snapshots
            trades: Trade events
            
        Returns:
            Calibration summary
        """
        # Extract features
        features = self._signal_model.extract_features(book_states, trades)
        if len(features) == 0:
            raise ValueError("No features extracted from calibration data")
        
        # Create target: did price move favorably?
        # For now, use fill + adverse selection as proxy
        # In full implementation, this would be price movement
        if "filled" not in observations.columns or "adverse_selection_bps" not in observations.columns:
            raise ValueError("Observations must have 'filled' and 'adverse_selection_bps' columns")
        
        # Align features with observations
        min_len = min(len(features), len(observations))
        features = features.iloc[:min_len].reset_index(drop=True)
        obs_aligned = observations.iloc[:min_len].reset_index(drop=True)
        
        # Target: 1 if filled with positive or zero adverse selection, 0 otherwise
        targets = ((obs_aligned["filled"] == 1) & (obs_aligned["adverse_selection_bps"] >= 0)).astype(int)
        
        # Fit model
        self._signal_model.fit(features, targets)
        
        # Compute calibration metrics
        predicted_probs = self._signal_model.predict_proba(features)
        accuracy = ((predicted_probs > 0.5) == targets).mean()
        
        self._calibration_summary = {
            "n_observations": int(len(observations)),
            "n_features": int(len(features)),
            "n_positive": int(targets.sum()),
            "n_negative": int(len(targets) - targets.sum()),
            "accuracy": float(accuracy),
            "mean_predicted_prob": float(predicted_probs.mean()),
            "feature_names": self._signal_model._feature_names,
        }
        
        return self._calibration_summary
    
    def get_signal_model(self) -> V11SignalModel:
        """Get calibrated signal model."""
        return self._signal_model
    
    def get_execution_model(self) -> V11ExecutionModel:
        """Get execution model."""
        return self._execution_model
    
    def get_calibration_summary(self) -> dict[str, Any]:
        """Get calibration summary."""
        return self._calibration_summary
