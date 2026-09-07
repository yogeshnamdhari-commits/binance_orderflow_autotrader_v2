"""V13 signal model — logistic regression with binned return calibration.

Same architecture as V12 (logistic regression, deterministic split) but with
V13 feature set and 2s horizon. Pre-registered config, no tuning on forward data.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import roc_auc_score, brier_score_loss

from .config import V13Config
from .features import V13_BASE_FEATURES


@dataclass(frozen=True)
class V13ModelConfig:
    feature_names: tuple = tuple(V13_BASE_FEATURES)
    model_type: str = "logistic"
    regularization_c: float = 1.0
    random_state: int = 42
    n_bins: int = 20


class V13SignalModel:
    """Logistic regression signal model with binned return calibration."""

    def __init__(self, config: V13ModelConfig | None = None):
        self._config = config or V13ModelConfig()
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
        self._val_auc: float | None = None
        self._test_auc: float | None = None
        self._train_auc: float | None = None
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

        train_probs = self.predict_proba(X_train)
        val_probs = self.predict_proba(X_val)
        test_probs = self.predict_proba(X_test)

        metrics = {
            "train_auc": float(roc_auc_score(y_train, train_probs)) if len(set(y_train)) > 1 else 0.5,
            "val_auc": float(roc_auc_score(y_val, val_probs)) if len(set(y_val)) > 1 else 0.5,
            "test_auc": float(roc_auc_score(y_test, test_probs)) if len(set(y_test)) > 1 else 0.5,
            "n_train": int(train_n),
            "n_val": int(val_n),
            "n_test": int(test_n),
            "n_positive": int(y.iloc[:train_n].sum()),
            "n_negative": int(train_n - y.iloc[:train_n].sum()),
            "brier": float(brier_score_loss(y_val, val_probs)) if len(y_val) > 0 else 0.0,
        }
        self._train_auc = metrics["train_auc"]
        self._val_auc = metrics["val_auc"]
        self._test_auc = metrics["test_auc"]
        self._feature_names = list(X.columns)

        if returns is not None:
            self._return_calibration = self._calibrate_returns(X, y, returns)

        return metrics

    def _calibrate_returns(self, X: pd.DataFrame, y: pd.Series, returns: pd.Series) -> dict:
        probs = self.predict_proba(X)
        bins = np.linspace(0, 1, self._config.n_bins + 1)
        calibration = {}
        for i in range(self._config.n_bins):
            mask = (probs >= bins[i]) & (probs < bins[i + 1])
            if mask.sum() > 0:
                key = f"{bins[i]:.3f}-{bins[i+1]:.3f}"
                calibration[key] = {
                    "mean_ret_bps": float(returns[mask].mean()),
                    "count": int(mask.sum()),
                }
        return calibration

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        X = X.replace([np.inf, -np.inf], 0.0).fillna(0.0)
        return self._pipeline.predict_proba(X)[:, 1]

    def predict_returns(self, X: pd.DataFrame) -> np.ndarray:
        probs = self.predict_proba(X)
        if not self._return_calibration:
            return probs * 0.0
        rets = []
        for p in probs:
            ret = 0.0
            for rng, cal in self._return_calibration.items():
                lo, hi = rng.split("-")
                if float(lo) <= p < float(hi):
                    ret = cal["mean_ret_bps"]
                    break
            rets.append(ret)
        return np.array(rets, dtype=float)

    def save(self, path: Path) -> str:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pipeline": self._pipeline,
            "feature_names": self._feature_names,
            "is_fitted": self._is_fitted,
            "val_auc": self._val_auc,
            "test_auc": self._test_auc,
            "train_auc": self._train_auc,
            "return_calibration": self._return_calibration,
        }
        joblib.dump(payload, path)
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @classmethod
    def load(cls, path: Path) -> "V13SignalModel":
        payload = joblib.load(Path(path))
        obj = cls()
        obj._pipeline = payload["pipeline"]
        obj._feature_names = payload["feature_names"]
        obj._is_fitted = payload["is_fitted"]
        obj._val_auc = payload.get("val_auc")
        obj._test_auc = payload.get("test_auc")
        obj._train_auc = payload.get("train_auc")
        obj._return_calibration = payload.get("return_calibration", {})
        return obj

    @property
    def is_fitted(self) -> bool:
        return self._is_fitted

    @property
    def val_auc(self) -> float | None:
        return self._val_auc

    @property
    def test_auc(self) -> float | None:
        return self._test_auc
