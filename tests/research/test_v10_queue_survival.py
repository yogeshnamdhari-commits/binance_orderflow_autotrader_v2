import numpy as np
import pandas as pd
import pytest

from app.v10_queue_survival import fit_queue_survival, predict_queue_fill_probability


def test_queue_conditioned_survival_uses_train_only_and_fallback():
    train = pd.DataFrame({
        "queue_ahead": [0.0, 0.0, 10.0, 10.0],
        "time_to_fill": [1.0, 2.0, 1.0, 2.0],
        "filled": [1, 0, 0, 1],
    })
    model = fit_queue_survival(train, bins=[0.0, 5.0, 20.0])
    pred = predict_queue_fill_probability(model, np.array([0.0, 10.0, 99.0]), 1.0)
    # Bucket 0 (q=0): 1 fill at t=1, 1 censored at t=2 -> KM fill prob at t=1 = 0.5
    assert pred[0] == pytest.approx(0.5)
    # Bucket 1 (q=10): 0 fills at t=1, 1 fill at t=2 -> KM fill prob at t=1 = 0.0
    assert pred[1] == pytest.approx(0.0)
    # q=99 out of range -> uses fallback (all data): 1/4 fill at t=1 -> 0.25
    assert pred[2] == pytest.approx(0.25)


def test_queue_survival_rejects_invalid_bins():
    train = pd.DataFrame({"queue_ahead": [0.0], "time_to_fill": [1.0], "filled": [1]})
    with pytest.raises(ValueError):
        fit_queue_survival(train, bins=[0.0, 0.0])
