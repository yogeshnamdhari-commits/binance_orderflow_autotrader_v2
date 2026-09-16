import numpy as np
import pytest

from app.v19.comparison import compare_to_v16


def test_comparison_detects_positive_increment():
    result = compare_to_v16([2.0, 3.0, 4.0], [1.0, 1.0, 1.0], bootstrap_samples=200, seed=1)
    assert result["incremental_mean_bps"] == pytest.approx(2.0)
    assert result["ci_low_bps"] >= 1.0
    assert result["ci_high_bps"] <= 3.0


def test_comparison_rejects_misalignment():
    with pytest.raises(ValueError):
        compare_to_v16(np.ones(3), np.ones(2))
