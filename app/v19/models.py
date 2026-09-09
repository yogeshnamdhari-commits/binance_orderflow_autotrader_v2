from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


@dataclass(frozen=True)
class ReturnModel:
    estimator: object
    feature_names: tuple[str, ...]

    def predict(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        if X.ndim != 2 or X.shape[1] != len(self.feature_names):
            raise ValueError("prediction feature shape does not match training feature names")
        return np.asarray(self.estimator.predict(X), dtype=float)


@dataclass(frozen=True)
class FillModel:
    estimator: object
    feature_names: tuple[str, ...]

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        if X.ndim != 2 or X.shape[1] != len(self.feature_names):
            raise ValueError("prediction feature shape does not match training feature names")
        return np.asarray(self.estimator.predict_proba(X)[:, 1], dtype=float)


def _validate(X: np.ndarray, y: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    if X.ndim != 2 or len(X) != len(y) or len(X) == 0:
        raise ValueError("X must be a non-empty 2-D array aligned with y")
    if not np.isfinite(X).all() or not np.isfinite(y).all():
        raise ValueError("training data must contain finite values")
    return X, y


def fit_return_model(X: np.ndarray, y: Sequence[float], feature_names: Sequence[str]) -> ReturnModel:
    X, y = _validate(X, y)
    names = tuple(feature_names)
    if X.shape[1] != len(names):
        raise ValueError("feature_names must match X columns")
    estimator = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
    estimator.fit(X, y)
    return ReturnModel(estimator, names)


def fit_fill_model(X: np.ndarray, filled: Sequence[int], feature_names: Sequence[str]) -> FillModel:
    X, y = _validate(X, filled)
    names = tuple(feature_names)
    if X.shape[1] != len(names):
        raise ValueError("feature_names must match X columns")
    classes = np.unique(y)
    if len(classes) != 2:
        raise ValueError("fill model requires both filled and unfilled observations")
    estimator = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=1000))
    estimator.fit(X, y.astype(int))
    return FillModel(estimator, names)
