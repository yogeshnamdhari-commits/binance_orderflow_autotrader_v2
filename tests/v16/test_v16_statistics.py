"""Regression tests for V16 statistical inference."""
from __future__ import annotations

import numpy as np

from app.v16.pipeline import _bootstrap_ci


def test_bootstrap_tstat_uses_bootstrap_se_not_se_of_bootstrap_se():
    """The bootstrap distribution SD is already an estimate of the SE of the mean."""
    returns = np.array([1.0, 2.0, 3.0, 4.0] * 25, dtype=float)
    result = _bootstrap_ci(returns, n_boot=4000, block_size=4, rng=np.random.default_rng(7))

    # The point estimate is 2.5 bps. A t-statistic around 8 is plausible;
    # dividing the bootstrap SE by sqrt(n) again produces an invalid statistic
    # roughly sqrt(n) times too large.
    assert 7.0 < result["tstat"] < 12.0


def test_bootstrap_tstat_scales_with_sample_size_correctly():
    """Doubling independent observations should increase t-stat by about sqrt(2)."""
    rng = np.random.default_rng(123)
    base = rng.normal(loc=1.0, scale=2.0, size=100)
    doubled = np.concatenate([base, rng.normal(loc=1.0, scale=2.0, size=100)])

    a = _bootstrap_ci(base, n_boot=3000, block_size=1, rng=np.random.default_rng(11))
    b = _bootstrap_ci(doubled, n_boot=3000, block_size=1, rng=np.random.default_rng(11))

    ratio = b["tstat"] / a["tstat"]
    assert 1.15 < ratio < 1.65
