"""V11 signal model — gradient-boosted classifier with return calibration.

Separates signal prediction from execution economics.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline


@dataclass(frozen=True)
class V11SignalConfig:
    """Frozen signal model configuration — pre-registered."""
    feature_window_ms: int = 1000
    prediction_horizon_ms: int = 500
    n_estimators: int = 100
    max_depth: int = 3
    learning_rate: float = 0.1
    min_samples_split: int = 1000
    min_samples_leaf: int = 500
    subsample: float = 0.8
    max_features: str = "sqrt"
    random_state: int = 42
    test_size: float = 0.15
    val_size: float = 0.15


class V11SignalModel:
    """Gradient-boosted order-flow signal model for V11."""

    def __init__(self, config: V11SignalConfig):
        self._config = config
        self._pipeline = Pipeline([
            ("scaler", StandardScaler()),
            ("clf", GradientBoostingClassifier(
                n_estimators=config.n_estimators,
                max_depth=config.max_depth,
                learning_rate=config.learning_rate,
                min_samples_split=config.min_samples_split,
                min_samples_leaf=config.min_samples_leaf,
                subsample=config.subsample,
                max_features=config.max_features,
                random_state=config.random_state,
            )),
        ])
        self._feature_names = [
            "ofi_l1", "ofi_norm_l1", "qi_l1", "di_l5", "di_l10",
            "mpd_bps", "spread_bps", "bid_cancel_bps", "ask_add_bps",
            "cancel_pressure", "tfi_500", "liq_depletion",
            "log_depth1", "log_depth5", "log_event_rate",
            "depth_slope_bps", "vol_500",
        ]
        self._calibrator: IsotonicRegression | None = None
        self._is_fitted = False
        self._train_auc: float | None = None
        self._val_auc: float | None = None
        self._return_calibration: dict[str, float] = {}

    def fit(self, X: pd.DataFrame, y: pd.Series, returns: pd.Series | None = None) -> dict[str, Any]:
        """Fit signal model with train/val/test split and return calibration.

        Args:
            X: Feature DataFrame
            y: Binary target (1 if price rose, 0 otherwise)
            returns: Actual forward returns in bps (for return calibration)

        Returns:
            Dict with training metrics
        """
        X = X[self._feature_names].copy()
        X = X.replace([np.inf, -np.inf], 0.0).fillna(0.0)

        # Chronological split: no shuffle
        n = len(X)
        test_n = int(n * self._config.test_size)
        val_n = int(n * self._config.val_size)
        train_n = n - test_n - val_n

        X_train, y_train = X.iloc[:train_n], y.iloc[:train_n]
        X_val, y_val = X.iloc[train_n:train_n + val_n], y.iloc[train_n:train_n + val_n]
        X_test, y_test = X.iloc[train_n + val_n:], y.iloc[train_n + val_n:]

        self._pipeline.fit(X_train, y_train)

        # Platt-like calibration on validation set (isotonic regression)
        val_probs = self._pipeline.predict_proba(X_val)[:, 1]
        self._calibrator = IsotonicRegression(out_of_bounds="clip")
        self._calibrator.fit(val_probs, y_val.values)

        self._is_fitted = True

        # Metrics
        train_probs = self.predict_proba(X_train)
        test_probs = self.predict_proba(X_test)
        self._train_auc = roc_auc_score(y_train, train_probs) if len(y_train.unique()) > 1 else 0.5
        self._val_auc = roc_auc_score(y_val, val_probs) if len(y_val.unique()) > 1 else 0.5
        test_auc = roc_auc_score(y_test, test_probs) if len(y_test.unique()) > 1 else 0.5

        # Return calibration: map prediction probability to expected return
        if returns is not None:
            cal_df = pd.DataFrame({
                "prob": self.predict_proba(X),
                "return": returns.reindex(X.index).fillna(0.0),
            })
            cal_df["prob_bin"] = pd.cut(cal_df["prob"], bins=10, labels=False)
            self._return_calibration = (
                cal_df.groupby("prob_bin")["return"].mean().to_dict()
            )

        return {
            "train_auc": float(self._train_auc) if self._train_auc is not None else 0.5,
            "val_auc": float(self._val_auc) if self._val_auc is not None else 0.5,
            "test_auc": float(test_auc),
            "n_train": int(len(X_train)),
            "n_val": int(len(X_val)),
            "n_test": int(len(X_test)),
            "n_positive": int(y.sum()),
            "n_negative": int(len(y) - y.sum()),
            "brier": float(brier_score_loss(y_test, test_probs)) if len(y_test) > 0 else None,
            "return_calibration_bins": len(self._return_calibration),
        }

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Predict calibrated probability of favorable price movement."""
        if not self._is_fitted:
            raise RuntimeError("Model must be fitted before prediction")
        X = X[self._feature_names].copy()
        X = X.replace([np.inf, -np.inf], 0.0).fillna(0.0)
        raw_probs = self._pipeline.predict_proba(X)[:, 1]
        if self._calibrator is not None:
            return self._calibrator.predict(raw_probs)
        return raw_probs

    def predict_returns(self, X: pd.DataFrame) -> np.ndarray:
        """Predict expected return in bps using calibrated return map."""
        if not self._is_fitted:
            raise RuntimeError("Model must be fitted before prediction")
        probs = self.predict_proba(X)
        returns = np.zeros(len(probs))
        for i, p in enumerate(probs):
            bin_idx = int(np.clip(p * 9.99, 0, 9))
            returns[i] = self._return_calibration.get(bin_idx, 0.0)
        return returns

    def predict(self, X: pd.DataFrame, threshold: float = 0.5) -> np.ndarray:
        """Predict binary class."""
        probs = self.predict_proba(X)
        return (probs > threshold).astype(int)

    def save(self, path: Path) -> None:
        """Save model artifact."""
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "config": self._config,
            "pipeline": self._pipeline,
            "calibrator": self._calibrator,
            "feature_names": self._feature_names,
            "train_auc": self._train_auc,
            "val_auc": self._val_auc,
            "is_fitted": self._is_fitted,
            "return_calibration": self._return_calibration,
        }, path)

    @classmethod
    def load(cls, path: Path) -> V11SignalModel:
        """Load frozen model artifact."""
        data = joblib.load(path)
        model = cls(data["config"])
        model._pipeline = data["pipeline"]
        model._calibrator = data["calibrator"]
        model._feature_names = data["feature_names"]
        model._train_auc = data["train_auc"]
        model._val_auc = data["val_auc"]
        model._is_fitted = data["is_fitted"]
        model._return_calibration = data.get("return_calibration", {})
        return model
