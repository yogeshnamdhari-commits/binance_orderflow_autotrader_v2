"""Statistical controls for the pre-declared V9 hypothesis family."""
from __future__ import annotations
import numpy as np


def benjamini_hochberg(p_values, alpha: float = 0.05):
    p = np.asarray(p_values, dtype=float)
    if p.ndim != 1 or len(p) == 0 or not np.all(np.isfinite(p)) or np.any((p < 0) | (p > 1)):
        raise ValueError("p_values must be a non-empty finite 1D array in [0,1]")
    if not (0 < alpha < 1):
        raise ValueError("alpha must be in (0,1)")
    m = len(p)
    order = np.argsort(p, kind="mergesort")
    ranked = p[order]
    factors = m / np.arange(1, m + 1)
    adjusted_ranked = np.minimum.accumulate((ranked * factors)[::-1])[::-1]
    adjusted_ranked = np.clip(adjusted_ranked, 0, 1)
    q = np.empty_like(p)
    q[order] = adjusted_ranked
    thresholds = alpha * np.arange(1, m + 1) / m
    passed = ranked <= thresholds
    reject_ranked = np.zeros(m, dtype=bool)
    if np.any(passed):
        reject_ranked[: np.where(passed)[0].max() + 1] = True
    reject = np.empty(m, dtype=bool)
    reject[order] = reject_ranked
    return q, reject
