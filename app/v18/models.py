from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


@dataclass
class ReturnModel:
    estimator: object
    feature_names: tuple[str, ...]

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.asarray(self.estimator.predict(X), dtype=float)


@dataclass
class FillModel:
    estimator: object
    feature_names: tuple[str, ...]

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
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
    estimator = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
    estimator.fit(X, y)
    return ReturnModel(estimator, tuple(feature_names))


def fit_fill_model(X: np.ndarray, filled: Sequence[int], feature_names: Sequence[str]) -> FillModel:
    X, y = _validate(X, filled)
    classes = np.unique(y)
    if len(classes) != 2:
        raise ValueError("fill model requires both filled and unfilled observations")
    estimator = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=1000))
    estimator.fit(X, y.astype(int))
    return FillModel(estimator, tuple(feature_names))


def expected_net_pnl(
    predicted_return: float,
    fill_probability: float,
    maker_round_trip_cost: float,
    taker_round_trip_cost: float,
    non_fill_opportunity_cost: float,
    maker_share: float = 1.0,
) -> float:
    if not 0.0 <= fill_probability <= 1.0:
        raise ValueError("fill_probability must be in [0, 1]")
    if not 0.0 <= maker_share <= 1.0:
        raise ValueError("maker_share must be in [0, 1]")
    expected_execution_cost = (
        maker_share * maker_round_trip_cost
        + (1.0 - maker_share) * taker_round_trip_cost
    )
    return (
        fill_probability * (predicted_return - expected_execution_cost)
        - (1.0 - fill_probability) * non_fill_opportunity_cost
    )
