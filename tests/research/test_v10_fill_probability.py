import numpy as np
from app.v10_fill_probability import empirical_fill_rate, brier_score


def test_empirical_fill_rate_is_conditional_and_bounded():
    assert empirical_fill_rate(np.array([1, 0, 1, 1])) == 0.75


def test_brier_score_compares_probability_to_outcome():
    score = brier_score(np.array([0.0, 1.0]), np.array([0, 1]))
    assert score == 0.0


def test_mismatched_inputs_fail():
    try:
        brier_score(np.array([0.5]), np.array([0, 1]))
    except ValueError:
        return
    assert False
