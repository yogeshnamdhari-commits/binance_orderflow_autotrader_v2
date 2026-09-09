from __future__ import annotations

from dataclasses import dataclass
from math import erf, sqrt
from typing import Sequence

import numpy as np

from .comparison import compare_to_v16


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reasons: tuple[str, ...]
    net_ev_bps: float
    realized_net_ev_bps: float
    ci_low_bps: float
    ci_high_bps: float
    p_value: float
    incremental_mean_bps: float
    incremental_ci_low_bps: float
    incremental_ci_high_bps: float
    incremental_p_value: float
    cost_stress: dict[float, float]
    regime_means: tuple[float, ...]


def _mean_ci(values: Sequence[float], seed: int = 19) -> tuple[float, float, float, float]:
    x = np.asarray(values, dtype=float)
    if x.size == 0 or not np.isfinite(x).all():
        raise ValueError("gate values must be finite and non-empty")
    mean = float(x.mean())
    rng = np.random.default_rng(seed)
    boot = rng.choice(x, size=(5000, len(x)), replace=True).mean(axis=1)
    lo, hi = np.quantile(boot, [0.025, 0.975])
    se = float(x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 1 else 0.0
    if se == 0.0:
        p = 0.0 if mean > 0 else 1.0
    else:
        z = abs(mean / se)
        p = float(2.0 * (1.0 - 0.5 * (1.0 + erf(z / sqrt(2.0)))))
    return mean, float(lo), float(hi), p


def run_cost_stress(net_outcomes: Sequence[float], multipliers: Sequence[float]) -> dict[float, float]:
    x = np.asarray(net_outcomes, dtype=float)
    if x.size == 0 or not np.isfinite(x).all():
        raise ValueError("net_outcomes must be finite and non-empty")
    gross_proxy = float(x.mean())
    return {float(m): gross_proxy / float(m) for m in multipliers}


def evaluate_gate(
    v19_outcomes: Sequence[float],
    v16_outcomes: Sequence[float],
    realized_outcomes: Sequence[float],
    regime_outcomes: Sequence[Sequence[float]],
    stress: dict[float, float],
    *,
    min_incremental_bps: float = 0.0,
    max_p_value: float = 0.05,
) -> GateResult:
    net, lo, hi, p = _mean_ci(v19_outcomes)
    realized = float(np.asarray(realized_outcomes, dtype=float).mean())
    relative = compare_to_v16(v19_outcomes, v16_outcomes)
    regime_means = tuple(float(np.asarray(r, dtype=float).mean()) for r in regime_outcomes if len(r))
    reasons: list[str] = []
    if relative["incremental_mean_bps"] <= min_incremental_bps:
        reasons.append("V19 does not improve net EV over frozen V16")
    if relative["ci_low_bps"] <= 0.0:
        reasons.append("V19 versus V16 confidence interval does not exclude zero")
    if relative["sign_test_pvalue"] > max_p_value:
        reasons.append("V19 versus V16 incremental result is not statistically significant")
    if net <= min_incremental_bps:
        reasons.append("net EV is not above the required economic threshold")
    if lo <= 0.0:
        reasons.append("V19 95% confidence interval does not exclude zero")
    if p > max_p_value:
        reasons.append("V19 economic result is not statistically significant")
    if not regime_means or any(x <= 0.0 for x in regime_means):
        reasons.append("at least one chronological regime is non-positive")
    if any(v <= 0.0 for v in stress.values()):
        reasons.append("cost stress removes the economic edge")
    return GateResult(
        not reasons, tuple(reasons), net, realized, lo, hi, p,
        float(relative["incremental_mean_bps"]), float(relative["ci_low_bps"]),
        float(relative["ci_high_bps"]), float(relative["sign_test_pvalue"]),
        dict(stress), regime_means,
    )
