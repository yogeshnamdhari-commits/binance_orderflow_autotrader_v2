import numpy as np
from research.v9_statistics import benjamini_hochberg


def test_bh_controls_false_discovery_rate_and_preserves_order():
    p = np.array([0.001, 0.01, 0.02, 0.8])
    q, reject = benjamini_hochberg(p, alpha=0.05)
    assert np.all(q >= 0) and np.all(q <= 1)
    assert reject.tolist() == [True, True, True, False]


def test_invalid_p_values_rejected():
    try:
        benjamini_hochberg(np.array([0.1, -0.1]), alpha=0.05)
    except ValueError:
        return
    assert False
