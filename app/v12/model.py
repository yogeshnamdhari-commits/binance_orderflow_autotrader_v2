"""V12 signal model — simple linear baseline with binned calibration.

Per Rule 9, we start with simple baselines and only use complexity if it
demonstrates genuine incremental out-of-sample value.

Baseline: logistic regression on V5 features (AUC ~0.666, gross ~0.174 bps).
This is the same well-tested V3/V5 model, NOT the overfitting gradient boosting from V11.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline


V12_FEATURES = [
    "ofi_l1", "ofi_norm_l1", "qi_l1", "di_l5", "di_l10",
    "mpd_bps", "spread_bps", "bid_cancel_bps", "ask_add_bps",
    "cancel_pressure", "tfi_500", "liq_depletion",
    "log_depth1", "log_depth5", "log_event_rate",
    "depth_slope_bps", "vol_500",
]


@dataclass(frozen=True)
class V12ModelConfig:
    """Frozen model configuration."""
    feature_names: tuple = tuple(V12_FEATURES)
    model_type: str = "logistic"
    regularization_c: float = 1.0
    random_state: int = 42
    n_bins: int = 20


class V12SignalModel:
    """Simple linear baseline signal model with binned return calibration."""

    def __init__(self, config: V12ModelConfig | None = None):
        self._config = config or V12ModelConfig()
        self._pipeline = Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(
                C=self._config.regularization_c,
                solver="lbfgs",
                max_iter=1000,
                random_state=self._config.random_state,
            )),
        ])
        self._feature_names = list(self._config.feature_names)
        self._is_fitted = False
        self._train_auc: float | None = None
        self._val_auc: float | None = None
        self._return_calibration: dict = {}

    def fit(self, X: pd.DataFrame, y: pd.Series, returns: pd.Series | None = None) -> dict:
        X = X[self._feature_names].copy()
        X = X.replace([np.inf, -np.inf], 0.0).fillna(0.0)
        n = len(X)
        test_n = int(n * 0.15)
        val_n = int(n * 0.15)
        train_n = n - test_n - val_n

        X_train, y_train = X.iloc[:train_n], y.iloc[:train_n]
        X_val, y_val = X.iloc[train_n:train_n + val_n], y.iloc[train_n:train_n + val_n]
        X_test, y_test = X.iloc[train_n + val_n:], y.iloc[train_n + val_n:]

        self._pipeline.fit(X_train, y_train)
        self._is_fitted = True

        from sklearn.metrics import roc_auc_score, brier_score_loss
        train_probs = self.predict_proba(X_train)
        val_probs = self.predict_proba(X_val)
        test_probs = self.predict_proba(X_test)

        self._train_auc = roc_auc_score(y_train, train_probs) if len(y_train.unique()) > 1 else 0.5
        self._val_auc = roc_auc_score(y_val, val_probs) if len(y_val.unique()) > 1 else 0.5
        test_auc = roc_auc_score(y_test, test_probs) if len(y_test.unique()) > 1 else 0.5

        if returns is not None:
            cal_df = pd.DataFrame({
                "prob": self.predict_proba(X),
                "return": returns.reindex(X.index).fillna(0.0),
            })
            cal_df["bin"] = pd.cut(cal_df["prob"], bins=self._config.n_bins, labels=False, include_lowest=True)
            self._return_calibration = cal_df.groupby("bin")["return"].mean().to_dict()

        return {
            "train_auc": float(self._train_auc),
            "val_auc": float(self._val_auc),
            "test_auc": float(test_auc),
            "n_train": int(len(X_train)),
            "n_val": int(len(X_val)),
            "n_test": int(len(X_test)),
            "n_positive": int(y.sum()),
            "n_negative": int(len(y) - y.sum()),
            "brier": float(brier_score_loss(y_test, test_probs)) if len(y_test) > 0 else None,
            "return_bins": len(self._return_calibration),
        }

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if not self._is_fitted:
            raise RuntimeError("Model must be fitted before prediction")
        X = X[self._feature_names].copy()
        X = X.replace([np.inf, -np.inf], 0.0).fillna(0.0)
        return self._pipeline.predict_proba(X)[:, 1]

    def predict_returns(self, X: pd.DataFrame) -> np.ndarray:
        probs = self.predict_proba(X)
        returns = np.zeros(len(probs))
        for i, p in enumerate(probs):
            bin_idx = int(np.clip(p * self._config.n_bins, 0, self._config.n_bins - 1))
            returns[i] = self._return_calibration.get(bin_idx, 0.0)
        return returns

    def save(self, path: Path) -> str:
        from hashlib import sha256
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "config": self._config,
            "pipeline": self._pipeline,
            "feature_names": self._feature_names,
            "train_auc": self._train_auc,
            "val_auc": self._val_auc,
            "is_fitted": self._is_fitted,
            "return_calibration": self._return_calibration,
        }, path)
        h = sha256()
        with open(path, "rb") as f:
            while chunk := f.read(8192):
                h.update(chunk)
        return h.hexdigest()

    @classmethod
    def load(cls, path: Path) -> "V12SignalModel":
        data = joblib.load(path)
        model = cls(data["config"])
        model._pipeline = data["pipeline"]
        model._feature_names = data["feature_names"]
        model._train_auc = data["train_auc"]
        model._val_auc = data["val_auc"]
        model._is_fitted = data["is_fitted"]
        model._return_calibration = data.get("return_calibration", {})
        return model
