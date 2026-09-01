"""Train-only, interpretable queue-conditioned fill-rate calibration."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class QueueFillModel:
    edges: tuple[float, ...]
    rates: tuple[float, ...]
    prior: float


def fit_queue_binned_fill_rates(train: pd.DataFrame, bins, prior: float = 0.5) -> QueueFillModel:
    if not (0 <= prior <= 1):
        raise ValueError("prior must be in [0,1]")
    if not {"queue_ahead", "filled"}.issubset(train.columns) or train.empty:
        raise ValueError("train must contain queue_ahead and filled")
    q = train["queue_ahead"].to_numpy(float)
    y = train["filled"].to_numpy(int)
    if not np.all(np.isfinite(q)) or np.any(q < 0) or not np.all(np.isin(y, [0, 1])):
        raise ValueError("invalid queue_ahead or filled values")
    edges = tuple(float(x) for x in bins)
    if len(edges) < 2 or any(b <= a for a, b in zip(edges, edges[1:])):
        raise ValueError("bins must be strictly increasing")
    bucket = np.searchsorted(edges, q, side="right") - 1
    rates = []
    for i in range(len(edges) - 1):
        mask = bucket == i
        rates.append(float(np.mean(y[mask])) if np.any(mask) else float(prior))
    return QueueFillModel(edges=edges, rates=tuple(rates), prior=float(prior))


def predict_queue_binned_fill_rate(model: QueueFillModel, queue_ahead) -> np.ndarray:
    q = np.asarray(queue_ahead, dtype=float)
    if not np.all(np.isfinite(q)) or np.any(q < 0):
        raise ValueError("queue_ahead must be finite and non-negative")
    idx = np.searchsorted(model.edges, q, side="right") - 1
    out = np.full(q.shape, model.prior, dtype=float)
    valid = (idx >= 0) & (idx < len(model.rates))
    out[valid] = np.asarray(model.rates)[idx[valid]]
    return np.clip(out, 0.0, 1.0)
