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
    n = len(x)
    block_size = max(1, int(n ** 0.5))
    rng = np.random.default_rng(seed)
    boot = []
    for _ in range(5000):
        starts = rng.integers(0, n, size=max(1, n // block_size))
        block = np.concatenate([np.roll(x, -s)[:block_size] for s in starts])
        boot.append(float(block[:n].mean()))
    lo, hi = float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))
    se = float(x.std(ddof=1) / np.sqrt(n)) if n > 1 else 0.0
    if se == 0.0:
        p = 0.0 if mean > 0 else 1.0
    else:
        z = abs(mean / se)
        p = float(2.0 * (1.0 - 0.5 * (1.0 + erf(z / sqrt(2.0)))))
    return mean, lo, hi, p


def run_cost_stress(
    predicted_returns_bps: Sequence[float],
    fill_probabilities: Sequence[float],
    config: V19Config,
) -> dict[float, float]:
    """Recompute expected net P&L under stressed execution costs.

    Each multiplier represents a scenario in which all cost components
    are increased proportionally from their baseline values. This is
    more realistic than scaling the mean net outcome by a constant.
    """
    pred = np.asarray(predicted_returns_bps, dtype=float)
    probs = np.asarray(fill_probabilities, dtype=float)
    if pred.size == 0 or probs.size == 0 or pred.size != probs.size:
        raise ValueError("predictions and fill probabilities must be non-empty and aligned")
    if not np.isfinite(pred).all() or not np.isfinite(probs).all():
        raise ValueError("cost stress inputs must be finite")
    if not (0.0 <= probs.min() <= probs.max() <= 1.0):
        raise ValueError("fill probabilities must be in [0, 1]")
    base_maker = config.maker_round_trip_cost_bps
    base_taker = config.taker_round_trip_cost_bps
    base_non_fill = config.non_fill_opportunity_cost_bps
    maker_share = config.maker_share
    results: dict[float, float] = {}
    for mult in config.cost_stress_multipliers:
        stressed_maker = base_maker * mult
        stressed_taker = base_taker * mult
        stressed_non_fill = base_non_fill * mult
        execution = maker_share * stressed_maker + (1.0 - maker_share) * stressed_taker
        net = probs * (pred - execution) - (1.0 - probs) * stressed_non_fill
        results[float(mult)] = float(np.mean(net))
    return results


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
