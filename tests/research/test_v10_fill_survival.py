import numpy as np
import pytest

from app.v10_fill_survival import fit_kaplan_meier


def test_kaplan_meier_retains_right_censoring():
    model = fit_kaplan_meier(
        np.array([1.0, 2.0, 2.0, 4.0]),
        np.array([1, 0, 1, 0]),
    )
    assert model.fill_probability(0.5) == 0.0
    assert model.fill_probability(1.0) == pytest.approx(0.25)
    assert model.fill_probability(2.0) == pytest.approx(0.625)


def test_kaplan_meier_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        fit_kaplan_meier([], [])
    with pytest.raises(ValueError):
        fit_kaplan_meier([1.0, -1.0], [1, 0])
    with pytest.raises(ValueError):
        fit_kaplan_meier([1.0, 2.0], [1, 2])
