"""V12 statistics — confidence intervals, permutation tests, regime analysis.

Dependence-aware statistical validation for financial time series.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats


@dataclass(frozen=True)
class V12StatisticalResult:
    """Statistical validation result."""
    mean_net_ev_bps: float
    std_net_ev_bps: float
    ci_95_lower: float
    ci_95_upper: float
    t_stat: float
    p_value: float
    cohens_d: float
    perm_pvalue: float
    n_observations: int
    n_positive: int
    significant: bool


def validate_statistics(
    net_ev: pd.Series,
    alpha: float = 0.05,
    n_permutations: int = 10000,
) -> V12StatisticalResult:
    """Run full statistical validation on net EV series."""
    x = net_ev.dropna().values
    n = len(x)
    if n == 0:
        return V12StatisticalResult(
            mean_net_ev_bps=0.0, std_net_ev_bps=0.0,
            ci_95_lower=0.0, ci_95_upper=0.0,
            t_stat=0.0, p_value=1.0, cohens_d=0.0,
            perm_pvalue=1.0, n_observations=0, n_positive=0,
            significant=False,
        )

    mean = float(np.mean(x))
    std = float(np.std(x, ddof=1)) if n > 1 else 0.0
    n_pos = int(np.sum(x > 0))

    if std > 0 and n > 1:
        t_stat = (mean - 0.0) / (std / np.sqrt(n))
        p_value = float(stats.t.sf(t_stat, df=n - 1))
    else:
        t_stat = 0.0
        p_value = 1.0 if mean <= 0 else 0.0

    # Bootstrap 95% CI
    if n > 1:
        rng = np.random.RandomState(42)
        boot_means = []
        for _ in range(10000):
            idx = rng.choice(n, size=n, replace=True)
            boot_means.append(float(np.mean(x[idx])))
        ci_lower = float(np.percentile(boot_means, 2.5))
        ci_upper = float(np.percentile(boot_means, 97.5))
    else:
        ci_lower = mean
        ci_upper = mean

    cohens_d = mean / std if std > 0 else 0.0

    # Permutation test (one-sided)
    rng = np.random.RandomState(42)
    count_extreme = 0
    for _ in range(n_permutations):
        perm = rng.choice([-1, 1], size=n) * x
        if np.mean(perm) >= mean:
            count_extreme += 1
    perm_pvalue = count_extreme / n_permutations

    significant = (p_value < alpha) and (ci_lower > 0)

    return V12StatisticalResult(
        mean_net_ev_bps=mean,
        std_net_ev_bps=std,
        ci_95_lower=ci_lower,
        ci_95_upper=ci_upper,
        t_stat=t_stat,
        p_value=p_value,
        cohens_d=cohens_d,
        perm_pvalue=perm_pvalue,
        n_observations=n,
        n_positive=n_pos,
        significant=significant,
    )


def analyze_regimes(
    net_ev: pd.Series,
    df: pd.DataFrame,
) -> dict[str, Any]:
    """Analyze net EV across predefined regimes."""
    regimes = {}

    if "spread_bps" in df.columns:
        high_spread = net_ev[df["spread_bps"] >= 0.02]
        low_spread = net_ev[df["spread_bps"] < 0.02]
        regimes["spread_regime"] = {
            "high_spread": {"n": len(high_spread), "mean_net_ev_bps": float(high_spread.mean()) if len(high_spread) > 0 else None, "positive_rate": float((high_spread > 0).mean()) if len(high_spread) > 0 else None},
            "low_spread": {"n": len(low_spread), "mean_net_ev_bps": float(low_spread.mean()) if len(low_spread) > 0 else None, "positive_rate": float((low_spread > 0).mean()) if len(low_spread) > 0 else None},
        }

    if "vol_500" in df.columns:
        vol_p50 = df["vol_500"].median()
        high_vol = net_ev[df["vol_500"] >= vol_p50]
        low_vol = net_ev[df["vol_500"] < vol_p50]
        regimes["vol_regime"] = {
            "high_vol": {"n": len(high_vol), "mean_net_ev_bps": float(high_vol.mean()) if len(high_vol) > 0 else None, "positive_rate": float((high_vol > 0).mean()) if len(high_vol) > 0 else None},
            "low_vol": {"n": len(low_vol), "mean_net_ev_bps": float(low_vol.mean()) if len(low_vol) > 0 else None, "positive_rate": float((low_vol > 0).mean()) if len(low_vol) > 0 else None},
        }

    terciles = pd.qcut(df.index, 3, labels=["early", "mid", "late"])
    regimes["time_regime"] = {}
    for label in ["early", "mid", "late"]:
        mask = terciles == label
        sub = net_ev[mask]
        regimes["time_regime"][label] = {
            "n": int(mask.sum()),
            "mean_net_ev_bps": float(sub.mean()) if len(sub) > 0 else None,
            "positive_rate": float((sub > 0).mean()) if len(sub) > 0 else None,
        }

    return regimes