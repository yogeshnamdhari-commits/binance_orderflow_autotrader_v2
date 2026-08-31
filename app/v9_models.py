"""Small, deterministic regularized logistic regression for V9 research.

No threshold selection or trading decision is performed here. Feature columns
are supplied explicitly by the caller so control/treatment specifications stay
frozen and auditable.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class LogisticModel:
    feature_names: tuple[str, ...]
    mean: np.ndarray
    scale: np.ndarray
    weights: np.ndarray
    intercept: float
    l2: float
    feature_names_in_: tuple[str, ...] = ()


def _matrix(X: pd.DataFrame):
    if not isinstance(X, pd.DataFrame) or X.empty:
        raise ValueError("X must be a non-empty DataFrame")
    if X.columns.duplicated().any():
        raise ValueError("duplicate feature names")
    a = X.to_numpy(dtype=float)
    if not np.isfinite(a).all():
        raise ValueError("X contains non-finite values")
    return a


def _fit(X: pd.DataFrame, y, l2=1.0, epochs=4000, lr=0.05):
    if l2 <= 0:
        raise ValueError("l2 must be positive")
    a = _matrix(X)
    y = np.asarray(y, dtype=float)
    if len(y) != len(a) or len(y) < 4:
        raise ValueError("X and y length mismatch or insufficient rows")
    if not np.isin(y, [0.0, 1.0]).all():
        raise ValueError("y must contain only 0/1")
    mean = a.mean(axis=0)
    scale = a.std(axis=0)
    scale[scale == 0] = 1.0
    z = (a - mean) / scale
    w = np.zeros(z.shape[1], dtype=float)
    b = 0.0
    for _ in range(epochs):
        eta = np.clip(z @ w + b, -40, 40)
        p = 1.0 / (1.0 + np.exp(-eta))
        grad_w = (z.T @ (p - y)) / len(y) + l2 * w
        grad_b = float(np.mean(p - y))
        w -= lr * grad_w
        b -= lr * grad_b
    names = tuple(map(str, X.columns))
    return LogisticModel(names, mean, scale, w, b, l2, names)


def fit_control(X_alt: pd.DataFrame, y, l2=1.0):
    return _fit(X_alt, y, l2=l2)


def fit_treatment(X_alt_btc: pd.DataFrame, y, l2=1.0):
    return _fit(X_alt_btc, y, l2=l2)


def predict_probability(model: LogisticModel, X: pd.DataFrame) -> np.ndarray:
    if tuple(map(str, X.columns)) != model.feature_names:
        raise ValueError("feature columns do not match fitted model")
    z = (_matrix(X) - model.mean) / model.scale
    eta = np.clip(z @ model.weights + model.intercept, -40, 40)
    return 1.0 / (1.0 + np.exp(-eta))
