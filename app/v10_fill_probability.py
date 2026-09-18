"""Simple empirical fill-probability baselines for V10 research."""
from __future__ import annotations
import numpy as np


def empirical_fill_rate(filled):
    y = np.asarray(filled, dtype=int)
    if y.ndim != 1 or len(y) == 0 or not np.all(np.isin(y, [0, 1])):
        raise ValueError("filled must be a non-empty binary vector")
    return float(np.mean(y))


def brier_score(probability, outcome):
    p = np.asarray(probability, dtype=float)
    y = np.asarray(outcome, dtype=int)
    if p.ndim != 1 or y.ndim != 1 or len(p) == 0 or len(p) != len(y):
        raise ValueError("probability and outcome must be non-empty vectors of equal length")
    if not np.all(np.isfinite(p)) or np.any((p < 0) | (p > 1)):
        raise ValueError("probability must be finite and in [0,1]")
    if not np.all(np.isin(y, [0, 1])):
        raise ValueError("outcome must be binary")
    return float(np.mean((p - y) ** 2))
