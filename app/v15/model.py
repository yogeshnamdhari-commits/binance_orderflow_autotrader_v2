"""V15 signal model — GradientBoostingRegressor predicting return magnitude.

Unlike V14 (logistic regression predicting direction), V15 directly predicts
the expected return in bps. The execution router then compares this against
all-in execution cost + safety margin.
"""
from __future__ import annotations

import hashlib
import numpy as np
import pandas as pd
from pathlib import Path

import joblib
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import mean_absolute_error, r2_score

from .config import V15Config
from .features import V15_FEATURES


class V15SignalModel:
    def __init__(self, config: V15Config | None = None):
        self._config = config or V15Config()
        self._pipeline = Pipeline([
            ("scaler", StandardScaler()),
            ("gbr", GradientBoostingRegressor(
                n_estimators=self._config.n_estimators,
                max_depth=self._config.max_depth,
                learning_rate=self._config.learning_rate,
                random_state=self._config.random_state,
            )),
        ])
        self._feature_names = list(V15_FEATURES)
        self._is_fitted = False
        self._val_mae = None
        self._test_mae = None
        self._train_mae = None
        self._val_r2 = None
        self._test_r2 = None

    def fit(self, X: pd.DataFrame, y: pd.Series) -> dict:
        X = X[self._feature_names].copy()
        X = X.replace([np.inf, -np.inf], 0.0).fillna(0.0)
        n = len(X)
        test_n = int(n * 0.15)
        val_n = int(n * 0.15)
        train_n = max(n - test_n - val_n, 1)

        X_train, y_train = X.iloc[:train_n], y.iloc[:train_n]
        X_val = X.iloc[train_n:train_n + val_n]
        X_test = X.iloc[train_n + val_n:]
        y_val = y.iloc[train_n:train_n + val_n]
        y_test = y.iloc[train_n + val_n:]

        self._pipeline.fit(X_train, y_train)
        self._is_fitted = True
        self._feature_names = list(X.columns)

        def mae(Xs, ys):
            if len(ys) == 0:
                return 0.0
            return float(mean_absolute_error(ys, self._pipeline.predict(Xs)))

        def r2(Xs, ys):
            if len(ys) <= 1:
                return 0.0
            return float(r2_score(ys, self._pipeline.predict(Xs)))

        metrics = {
            "train_mae": mae(X_train, y_train),
            "val_mae": mae(X_val, y_val),
            "test_mae": mae(X_test, y_test),
            "train_r2": r2(X_train, y_train),
            "val_r2": r2(X_val, y_val),
            "test_r2": r2(X_test, y_test),
            "n_train": train_n, "n_val": val_n, "n_test": test_n,
        }
        self._train_mae = metrics["train_mae"]
        self._val_mae = metrics["val_mae"]
        self._test_mae = metrics["test_mae"]
        self._val_r2 = metrics["val_r2"]
        self._test_r2 = metrics["test_r2"]
        return metrics

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        X = X.replace([np.inf, -np.inf], 0.0).fillna(0.0)
        return self._pipeline.predict(X)

    def save(self, path: Path) -> str:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "pipeline": self._pipeline,
            "feature_names": self._feature_names,
            "is_fitted": self._is_fitted,
            "val_mae": self._val_mae,
            "test_mae": self._test_mae,
            "train_mae": self._train_mae,
            "val_r2": self._val_r2,
            "test_r2": self._test_r2,
        }, path)
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @classmethod
    def load(cls, path: Path) -> "V15SignalModel":
        payload = joblib.load(Path(path))
        obj = cls()
        obj._pipeline = payload["pipeline"]
        obj._feature_names = payload["feature_names"]
        obj._is_fitted = payload["is_fitted"]
        obj._val_mae = payload.get("val_mae")
        obj._test_mae = payload.get("test_mae")
        obj._train_mae = payload.get("train_mae")
        obj._val_r2 = payload.get("val_r2")
        obj._test_r2 = payload.get("test_r2")
        return obj
