"""Non-parametric fill-time survival estimates for V10 passive-order research."""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Iterable, Tuple


@dataclass(frozen=True)
class KaplanMeierResult:
    n: int
    events: int
    probability: float
    survival: float
    variance: float
    ci_low: float
    ci_high: float


def kaplan_meier_fill_probability(
    observations: Iterable[Tuple[float, bool]], *, horizon: float, z: float = 1.96
) -> KaplanMeierResult:
    """Estimate P(fill <= horizon) from (time, filled) observations."""
    if horizon <= 0:
        raise ValueError("horizon must be positive")
    if z <= 0:
        raise ValueError("z must be positive")

    rows = []
    for time, filled in observations:
        time = float(time)
        if time <= 0:
            raise ValueError("observation times must be positive")
        rows.append((time, bool(filled)))
    if not rows:
        raise ValueError("at least one observation is required")

    n_total = len(rows)
    survival = 1.0
    greenwood = 0.0
    events = 0
    at_risk = n_total

    for time in sorted({t for t, _ in rows if t <= horizon}):
        d = sum(1 for t, filled in rows if t == time and filled)
        c = sum(1 for t, filled in rows if t == time and not filled)
        if at_risk <= 0:
            break
        if d:
            events += d
            if d < at_risk:
                survival *= 1.0 - d / at_risk
                greenwood += d / (at_risk * (at_risk - d))
            else:
                survival = 0.0
        at_risk -= d + c

    probability = 1.0 - survival
    variance = survival * survival * greenwood
    se = sqrt(max(0.0, variance))
    ci_low = max(0.0, probability - z * se)
    ci_high = min(1.0, probability + z * se)

    return KaplanMeierResult(
        n=n_total,
        events=events,
        probability=probability,
        survival=survival,
        variance=variance,
        ci_low=ci_low,
        ci_high=ci_high,
    )
