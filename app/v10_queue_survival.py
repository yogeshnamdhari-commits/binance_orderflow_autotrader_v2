"""Queue-conditioned fill-time survival model for V10 research."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd

from .v10_fill_survival import SurvivalCurve, fit_kaplan_meier


@dataclass(frozen=True)
class QueueSurvivalModel:
    edges: tuple[float, ...]
    curves: tuple[SurvivalCurve | None, ...]
    fallback: SurvivalCurve


def fit_queue_survival(train: pd.DataFrame, bins, *, time_col: str = "time_to_fill", filled_col: str = "filled") -> QueueSurvivalModel:
    required = {"queue_ahead", time_col, filled_col}
    if not required.issubset(train.columns) or train.empty:
        raise ValueError(f"train must contain {sorted(required)}")
    q = train["queue_ahead"].to_numpy(float)
    if not np.all(np.isfinite(q)) or np.any(q < 0):
        raise ValueError("queue_ahead must be finite and non-negative")
    edges = tuple(float(x) for x in bins)
    if len(edges) < 2 or any(b <= a for a, b in zip(edges, edges[1:])):
        raise ValueError("bins must be strictly increasing")

    fallback = fit_kaplan_meier(train[time_col].to_numpy(float), train[filled_col].to_numpy(int))
    bucket = np.searchsorted(edges, q, side="right") - 1
    curves: list[SurvivalCurve | None] = []
    for i in range(len(edges) - 1):
        mask = bucket == i
        curves.append(
            fit_kaplan_meier(train.loc[mask, time_col].to_numpy(float), train.loc[mask, filled_col].to_numpy(int))
            if np.any(mask) else None
        )
    return QueueSurvivalModel(edges=edges, curves=tuple(curves), fallback=fallback)


def predict_queue_fill_probability(model: QueueSurvivalModel, queue_ahead, horizon: float) -> np.ndarray:
    q = np.asarray(queue_ahead, dtype=float)
    if not np.all(np.isfinite(q)) or np.any(q < 0):
        raise ValueError("queue_ahead must be finite and non-negative")
    idx = np.searchsorted(model.edges, q, side="right") - 1
    out = np.empty(q.shape, dtype=float)
    fallback = model.fallback.fill_probability(horizon)
    for i, bucket in enumerate(idx):
        curve = model.curves[bucket] if 0 <= bucket < len(model.curves) else None
        out[i] = curve.fill_probability(horizon) if curve is not None else fallback
    return np.clip(out, 0.0, 1.0)
