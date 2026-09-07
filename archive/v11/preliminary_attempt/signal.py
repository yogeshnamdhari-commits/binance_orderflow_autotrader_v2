"""V11 order-flow signal model.

Separates signal edge from execution economics.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline


@dataclass(frozen=True)
class V11SignalConfig:
    """Frozen signal model configuration."""
    feature_window_ms: int = 1000
    prediction_horizon_ms: int = 1000
    min_spread_bps: float = 0.001
    regularization_c: float = 1.0
    class_weight: str = "balanced"


class V11SignalModel:
    """Order-flow signal model for V11.
    
    Separates signal prediction from execution economics.
    """
    
    def __init__(self, config: V11SignalConfig):
        self._config = config
        self._pipeline = Pipeline([
            ("scaler", StandardScaler()),
            ("classifier", LogisticRegression(
                C=config.regularization_c,
                class_weight=config.class_weight,
                solver="lbfgs",
                max_iter=1000,
            )),
        ])
        self._feature_names = ["order_flow_imbalance", "depth_imbalance", "trade_direction"]
        self._is_fitted = False
    
    def extract_features(self, book_states: list[Any], trades: list[Any]) -> pd.DataFrame:
        """Extract order flow features from book states and trades.
        
        Args:
            book_states: List of book state snapshots
            trades: List of trade events
            
        Returns:
            DataFrame with features for each decision point
        """
        if not book_states:
            return pd.DataFrame(columns=self._feature_names + ["timestamp"])
        
        features = []
        for i, bs in enumerate(book_states):
            ts = bs.timestamp
            
            # Order flow imbalance (buy vs sell aggression)
            window_start = ts - pd.Timedelta(milliseconds=self._config.feature_window_ms)
            window_trades = [t for t in trades if window_start <= t.timestamp < ts]
            
            buy_volume = sum(t.qty for t in window_trades if not t.buyer_is_maker)
            sell_volume = sum(t.qty for t in window_trades if t.buyer_is_maker)
            total_volume = buy_volume + sell_volume
            order_flow_imbalance = (buy_volume - sell_volume) / total_volume if total_volume > 0 else 0.0
            
            # Depth imbalance
            bid_depth = bs.bid_size
            ask_depth = bs.ask_size
            total_depth = bid_depth + ask_depth
            depth_imbalance = (bid_depth - ask_depth) / total_depth if total_depth > 0 else 0.0
            
            # Trade direction (recent)
            if window_trades:
                recent_buy_ratio = sum(1 for t in window_trades if not t.buyer_is_maker) / len(window_trades)
            else:
                recent_buy_ratio = 0.5
            
            features.append({
                "timestamp": ts,
                "order_flow_imbalance": order_flow_imbalance,
                "depth_imbalance": depth_imbalance,
                "trade_direction": recent_buy_ratio,
            })
        
        return pd.DataFrame(features)
    
    def fit(self, features: pd.DataFrame, targets: pd.Series) -> None:
        """Fit signal model on calibration data.
        
        Args:
            features: Feature DataFrame
            targets: Binary target (1 if price moved favorably, 0 otherwise)
        """
        self._pipeline.fit(features[self._feature_names], targets)
        self._is_fitted = True
    
    def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
        """Predict probability of favorable price movement."""
        if not self._is_fitted:
            raise RuntimeError("Model must be fitted before prediction")
        return self._pipeline.predict_proba(features[self._feature_names])[:, 1]
    
    def save(self, path: Path) -> None:
        """Save model to disk."""
        import joblib
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "config": self._config,
            "pipeline": self._pipeline,
            "feature_names": self._feature_names,
        }, path)
    
    @classmethod
    def load(cls, path: Path) -> V11SignalModel:
        """Load model from disk."""
        import joblib
        data = joblib.load(path)
        model = cls(data["config"])
        model._pipeline = data["pipeline"]
        model._feature_names = data["feature_names"]
        model._is_fitted = True
        return model
