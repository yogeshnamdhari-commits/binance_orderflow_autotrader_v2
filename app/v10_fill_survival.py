"""Non-parametric fill-time survival estimator for V10 research.

Uses Kaplan-Meier estimation so censored (unfilled-by-horizon) orders are retained
rather than incorrectly treated as zero-time failures. No strategy parameters are
learned from the evaluation sample.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class SurvivalCurve:
    times: tuple[float, ...]
    survival: tuple[float, ...]
    events: tuple[int, ...]
    at_risk: tuple[int, ...]

    def fill_probability(self, horizon: float) -> float:
        h = float(horizon)
        if not np.isfinite(h) or h < 0:
            raise ValueError("horizon must be finite and non-negative")
        if not self.times:
            return 0.0
        idx = np.searchsorted(np.asarray(self.times), h, side="right") - 1
        if idx < 0:
            return 0.0
        return float(1.0 - self.survival[idx])


def fit_kaplan_meier(time_to_fill, filled) -> SurvivalCurve:
    """Fit P(T_fill <= t) from durations and right-censoring indicators.

    ``time_to_fill`` is the observed duration to fill or censoring horizon.
    ``filled`` is 1 when the order filled at that duration, otherwise 0.
    """
    t = np.asarray(time_to_fill, dtype=float)
    e = np.asarray(filled, dtype=int)
    if t.ndim != 1 or e.ndim != 1 or len(t) == 0 or len(t) != len(e):
        raise ValueError("time_to_fill and filled must be non-empty vectors of equal length")
    if not np.all(np.isfinite(t)) or np.any(t < 0):
        raise ValueError("time_to_fill must be finite and non-negative")
    if not np.all(np.isin(e, [0, 1])):
        raise ValueError("filled must be binary")

    times = np.sort(np.unique(t))
    survival = []
    events = []
    at_risk = []
    s = 1.0
    for time in times:
        risk = int(np.count_nonzero(t >= time))
        d = int(np.count_nonzero((t == time) & (e == 1)))
        if risk > 0 and d > 0:
            s *= 1.0 - d / risk
        at_risk.append(risk)
        events.append(d)
        survival.append(float(np.clip(s, 0.0, 1.0)))
    return SurvivalCurve(tuple(times.tolist()), tuple(survival), tuple(events), tuple(at_risk))
