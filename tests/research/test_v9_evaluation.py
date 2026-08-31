import numpy as np
from research.v9_evaluation import evaluate_incremental


def test_incremental_evaluation_reports_oos_metrics():
    y = np.array([0, 0, 1, 1])
    c = np.array([.4, .4, .6, .6])
    t = np.array([.2, .3, .7, .8])
    r = evaluate_incremental(c, t, y)
    assert set(["control_log_loss", "treatment_log_loss", "delta_log_loss", "control_accuracy", "treatment_accuracy"]).issubset(r)
    assert r["delta_log_loss"] > 0


def test_invalid_probabilities_are_rejected():
    y = np.array([0, 1])
    try:
        evaluate_incremental(np.array([-.1, .5]), np.array([.5, .5]), y)
    except ValueError:
        return
    assert False, "invalid probabilities must be rejected"
