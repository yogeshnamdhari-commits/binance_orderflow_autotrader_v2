"""Leakage-safe metrics for comparing V9 control and treatment models."""
from __future__ import annotations
import math
import numpy as np


def _validate(prob, y):
    p = np.asarray(prob, dtype=float)
    y = np.asarray(y, dtype=int)
    if p.ndim != 1 or y.ndim != 1 or len(p) != len(y) or len(p) == 0:
        raise ValueError("probabilities and labels must be non-empty 1D arrays of equal length")
    if not np.all(np.isfinite(p)) or np.any((p < 0) | (p > 1)):
        raise ValueError("probabilities must be finite and in [0,1]")
    if not np.all(np.isin(y, [0, 1])):
        raise ValueError("labels must be binary")
    return p, y


def _log_loss(p, y):
    eps = np.finfo(float).eps
    q = np.clip(p, eps, 1.0 - eps)
    return float(-np.mean(y * np.log(q) + (1 - y) * np.log1p(-q)))


def evaluate_incremental(control_prob, treatment_prob, y):
    c, y = _validate(control_prob, y)
    t, y2 = _validate(treatment_prob, y)
    if not np.array_equal(y, y2):
        raise ValueError("control and treatment labels differ")
    cl = _log_loss(c, y)
    tl = _log_loss(t, y)
    return {
        "n": int(len(y)),
        "control_log_loss": cl,
        "treatment_log_loss": tl,
        "delta_log_loss": cl - tl,
        "control_accuracy": float(np.mean((c >= 0.5) == y)),
        "treatment_accuracy": float(np.mean((t >= 0.5) == y)),
    }
