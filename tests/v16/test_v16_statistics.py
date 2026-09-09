"""Regression tests for V16 statistical inference."""
from __future__ import annotations

import numpy as np

from app.v16.pipeline import _bootstrap_ci


def test_bootstrap_tstat_uses_bootstrap_se_not_se_of_bootstrap_se():
    """The bootstrap distribution SD is already an estimate of the SE of the mean."""
    returns = np.random.default_rng(42).normal(loc=1.0, scale=2.0, size=100)
    result = _bootstrap_ci(returns, n_boot=4000, block_size=4, rng=np.random.default_rng(11))

    # The bootstrap distribution SD is the estimated SE of the sample mean.
    # Dividing it by sqrt(n) again makes the t-statistic about sqrt(n) too large.
    assert 40.0 < result["tstat"] < 70.0


def test_bootstrap_tstat_scales_with_sample_size_correctly():
    """Doubling independent observations should increase t-stat by about sqrt(2)."""
    rng = np.random.default_rng(123)
    base = rng.normal(loc=1.0, scale=2.0, size=100)
    doubled = np.concatenate([base, rng.normal(loc=1.0, scale=2.0, size=100)])

    a = _bootstrap_ci(base, n_boot=3000, block_size=1, rng=np.random.default_rng(11))
    b = _bootstrap_ci(doubled, n_boot=3000, block_size=1, rng=np.random.default_rng(11))

    ratio = b["tstat"] / a["tstat"]
    assert 1.15 < ratio < 1.65
