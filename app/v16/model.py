"""V16 signal models — return magnitude (GBR) + fill probability (Logistic)."""
from __future__ import annotations

import hashlib
import numpy as np
import pandas as pd
from pathlib import Path

import joblib
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import roc_auc_score, brier_score_loss, mean_absolute_error, r2_score

from .config import V16Config
from .features import V16_FEATURES


class V16ReturnModel:
    """Predicts return magnitude in bps."""
    def __init__(self, config: V16Config | None = None):
        self._config = config or V16Config()
        self._pipeline = Pipeline([
            ("scaler", StandardScaler()),
            ("gbr", GradientBoostingRegressor(
                n_estimators=self._config.n_estimators,
                max_depth=self._config.max_depth,
                learning_rate=self._config.learning_rate,
                random_state=self._config.random_state,
            )),
        ])
        self._feature_names = list(V16_FEATURES)
        self._is_fitted = False
        self._train_mae = None
        self._val_mae = None
        self._test_mae = None
        self._train_r2 = None
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

        metrics = {
            "train_mae": float(mean_absolute_error(y_train, self._pipeline.predict(X_train))) if len(y_train) > 0 else 0.0,
            "val_mae": float(mean_absolute_error(y_val, self._pipeline.predict(X_val))) if len(y_val) > 0 else 0.0,
            "test_mae": float(mean_absolute_error(y_test, self._pipeline.predict(X_test))) if len(y_test) > 0 else 0.0,
            "train_r2": float(r2_score(y_train, self._pipeline.predict(X_train))) if len(y_train) > 1 else 0.0,
            "val_r2": float(r2_score(y_val, self._pipeline.predict(X_val))) if len(y_val) > 1 else 0.0,
            "test_r2": float(r2_score(y_test, self._pipeline.predict(X_test))) if len(y_test) > 1 else 0.0,
            "n_train": train_n, "n_val": val_n, "n_test": test_n,
        }
        self._train_mae = metrics["train_mae"]
        self._val_mae = metrics["val_mae"]
        self._test_mae = metrics["test_mae"]
        self._train_r2 = metrics["train_r2"]
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
            "train_mae": self._train_mae,
            "val_mae": self._val_mae,
            "test_mae": self._test_mae,
            "train_r2": self._train_r2,
            "val_r2": self._val_r2,
            "test_r2": self._test_r2,
        }, path)
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @classmethod
    def load(cls, path: Path) -> "V16ReturnModel":
        payload = joblib.load(Path(path))
        obj = cls()
        obj._pipeline = payload["pipeline"]
        obj._feature_names = payload["feature_names"]
        obj._is_fitted = payload["is_fitted"]
        obj._train_mae = payload.get("train_mae")
        obj._val_mae = payload.get("val_mae")
        obj._test_mae = payload.get("test_mae")
        obj._train_r2 = payload.get("train_r2")
        obj._val_r2 = payload.get("val_r2")
        obj._test_r2 = payload.get("test_r2")
        return obj


class V16FillProbabilityModel:
    """Predicts fill probability (0-1) for a maker order."""
    def __init__(self, config: V16Config | None = None):
        self._config = config or V16Config()
        self._pipeline = Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000, random_state=self._config.random_state)),
        ])
        self._feature_names = list(V16_FEATURES)
        self._is_fitted = False
        self._val_auc = None
        self._test_auc = None

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

        def auc(Xs, ys):
            if len(set(ys)) < 2:
                return 0.5
            try:
                return float(roc_auc_score(ys, self._pipeline.predict_proba(Xs)[:, 1]))
            except Exception:
                return 0.5

        metrics = {
            "train_auc": auc(X_train, y_train),
            "val_auc": auc(X_val, y_val),
            "test_auc": auc(X_test, y_test),
            "n_train": train_n, "n_val": val_n, "n_test": test_n,
            "brier": float(brier_score_loss(y_val, self._pipeline.predict_proba(X_val)[:, 1])) if len(y_val) > 0 else 0.0,
        }
        self._val_auc = metrics["val_auc"]
        self._test_auc = metrics["test_auc"]
        return metrics

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        X = X.replace([np.inf, -np.inf], 0.0).fillna(0.0)
        return self._pipeline.predict_proba(X)[:, 1]

    def save(self, path: Path) -> str:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "pipeline": self._pipeline,
            "feature_names": self._feature_names,
            "is_fitted": self._is_fitted,
            "val_auc": self._val_auc,
            "test_auc": self._test_auc,
        }, path)
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @classmethod
    def load(cls, path: Path) -> "V16FillProbabilityModel":
        payload = joblib.load(Path(path))
        obj = cls()
        obj._pipeline = payload["pipeline"]
        obj._feature_names = payload["feature_names"]
        obj._is_fitted = payload["is_fitted"]
        obj._val_auc = payload.get("val_auc")
        obj._test_auc = payload.get("test_auc")
        return obj
