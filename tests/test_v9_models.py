import numpy as np
import pandas as pd
from app.v9_models import fit_control, fit_treatment, predict_probability


def test_control_and_treatment_return_probabilities_in_unit_interval():
    x = pd.DataFrame({"alt_ret_1m": [-.01, -.005, 0, .005, .01], "btc_ret_1m": [-.02, -.01, 0, .01, .02]})
    y = np.array([0, 0, 0, 1, 1])
    c = fit_control(x[["alt_ret_1m"]], y)
    t = fit_treatment(x, y)
    assert np.all((predict_probability(c, x[["alt_ret_1m"]]) >= 0) & (predict_probability(c, x[["alt_ret_1m"]]) <= 1))
    assert np.all((predict_probability(t, x) >= 0) & (predict_probability(t, x) <= 1))


def test_treatment_metadata_records_feature_sets():
    x = pd.DataFrame({"alt_ret_1m": [-.01, -.005, 0, .005, .01], "btc_ret_1m": [-.02, -.01, 0, .01, .02]})
    y = np.array([0, 0, 0, 1, 1])
    model = fit_treatment(x, y)
    assert model.feature_names_in_.tolist() == ["alt_ret_1m", "btc_ret_1m"]
