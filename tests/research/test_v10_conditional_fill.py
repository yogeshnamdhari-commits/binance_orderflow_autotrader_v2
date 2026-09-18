import numpy as np
import pandas as pd
from app.v10_conditional_fill import fit_queue_binned_fill_rates, predict_queue_binned_fill_rate


def test_queue_binned_fill_rates_are_fit_from_training_rows_only():
    train = pd.DataFrame({"queue_ahead": [0, 0, 1, 1], "filled": [1, 1, 0, 0]})
    model = fit_queue_binned_fill_rates(train, bins=[0, 1, 2])
    assert predict_queue_binned_fill_rate(model, np.array([0.0]))[0] == 1.0
    assert predict_queue_binned_fill_rate(model, np.array([1.0]))[0] == 0.0


def test_empty_bin_uses_explicit_prior_not_future_observations():
    train = pd.DataFrame({"queue_ahead": [0, 0], "filled": [1, 0]})
    model = fit_queue_binned_fill_rates(train, bins=[0, 1, 2], prior=0.25)
    prediction = predict_queue_binned_fill_rate(model, np.array([1.5]))[0]
    assert prediction == 0.25
