"""V14 signal model — logistic regression on 10s order-flow features."""
from __future__ import annotations

import hashlib
import numpy as np
import pandas as pd
from pathlib import Path

import joblib
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import roc_auc_score, brier_score_loss

from .config import V14Config
from .features import V14_FEATURES


class V14SignalModel:
    def __init__(self, config: V14Config | None = None):
        self._config = config or V14Config()
        self._pipeline = Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(
                C=self._config.regularization_c, solver="lbfgs",
                max_iter=1000, random_state=self._config.random_state,
            )),
        ])
        self._feature_names = list(V14_FEATURES)
        self._is_fitted = False
        self._val_auc = None
        self._test_auc = None
        self._train_auc = None
        self._return_calibration = {}

    def fit(self, X: pd.DataFrame, y: pd.Series, returns: pd.Series | None = None) -> dict:
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
            p = self.predict_proba(Xs)
            try:
                return float(roc_auc_score(ys, p))
            except Exception:
                return 0.5

        metrics = {
            "train_auc": auc(X_train, y_train),
            "val_auc": auc(X_val, y_val),
            "test_auc": auc(X_test, y_test),
            "n_train": train_n, "n_val": val_n, "n_test": test_n,
            "n_positive": int(y.iloc[:train_n].sum()),
            "n_negative": int(train_n - y.iloc[:train_n].sum()),
            "brier": float(brier_score_loss(y_val, self.predict_proba(X_val))) if len(y_val) > 0 else 0.0,
        }
        self._train_auc = metrics["train_auc"]
        self._val_auc = metrics["val_auc"]
        self._test_auc = metrics["test_auc"]

        if returns is not None:
            probs = self.predict_proba(X)
            ret_vals = returns.values if hasattr(returns, 'values') else np.asarray(returns)
            valid = ~np.isnan(ret_vals)
            self._return_calibration = self._calibrate_returns(probs[valid], pd.Series(ret_vals[valid]))
        return metrics

    def _calibrate_returns(self, probs: np.ndarray, returns: pd.Series) -> dict:
        n_bins = 20
        bins = np.linspace(0, 1, n_bins + 1)
        cal = {}
        for i in range(n_bins):
            mask = (probs >= bins[i]) & (probs < bins[i + 1])
            if mask.sum() > 0:
                key = f"{bins[i]:.3f}-{bins[i+1]:.3f}"
                cal[key] = {"mean_ret_bps": float(returns.values[mask].mean()), "count": int(mask.sum())}
        return cal

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        X = X.replace([np.inf, -np.inf], 0.0).fillna(0.0)
        return self._pipeline.predict_proba(X)[:, 1]

    def predict_returns(self, X: pd.DataFrame) -> np.ndarray:
        probs = self.predict_proba(X)
        if not self._return_calibration:
            return probs * 0.0
        rets = []
        for p in probs:
            r = 0.0
            for rng, cal in self._return_calibration.items():
                lo, hi = rng.split("-")
                if float(lo) <= p < float(hi):
                    r = cal["mean_ret_bps"]
                    break
            rets.append(r)
        return np.array(rets, dtype=float)

    def save(self, path: Path) -> str:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "pipeline": self._pipeline,
            "feature_names": self._feature_names,
            "is_fitted": self._is_fitted,
            "val_auc": self._val_auc,
            "test_auc": self._test_auc,
            "train_auc": self._train_auc,
            "return_calibration": self._return_calibration,
        }, path)
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @classmethod
    def load(cls, path: Path) -> "V14SignalModel":
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
