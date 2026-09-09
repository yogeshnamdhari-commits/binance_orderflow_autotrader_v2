from __future__ import annotations

from math import comb
from typing import Sequence

import numpy as np


def compare_to_v16(v19: Sequence[float], v16: Sequence[float], *, bootstrap_samples: int = 5000, seed: int = 19) -> dict[str, float]:
    """Compare aligned trade outcomes without assuming independence between versions."""
    if bootstrap_samples <= 0:
        raise ValueError("bootstrap_samples must be positive")
    a = np.asarray(v19, dtype=float)
    b = np.asarray(v16, dtype=float)
    if a.ndim != 1 or b.ndim != 1 or len(a) == 0 or len(a) != len(b):
        raise ValueError("v19 and v16 outcomes must be non-empty aligned 1-D arrays")
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("comparison outcomes must be finite")
    d = a - b
    mean = float(np.mean(d))
    rng = np.random.default_rng(seed)
    samples = rng.choice(d, size=(bootstrap_samples, len(d)), replace=True).mean(axis=1)
    lo, hi = np.quantile(samples, [0.025, 0.975])
    nonzero = d[d != 0]
    if len(nonzero) == 0:
        p = 1.0
    else:
        positives = int(np.sum(nonzero > 0))
        n = len(nonzero)
        k = min(positives, n - positives)
        p = min(1.0, 2.0 * sum(comb(n, i) for i in range(k + 1)) / (2.0 ** n))
    return {
        "incremental_mean_bps": mean,
        "ci_low_bps": float(lo),
        "ci_high_bps": float(hi),
        "sign_test_pvalue": float(p),
        "n": float(len(d)),
    }
