import numpy as np
import pytest

from app.v19.models import fit_fill_model, fit_return_model


def test_return_model_predicts_training_shape():
    X = np.array([[0.0], [1.0], [2.0], [3.0]])
    y = np.array([0.0, 1.0, 2.0, 3.0])
    model = fit_return_model(X, y, ["ofi_1"])
    assert model.predict(X).shape == (4,)


def test_fill_model_requires_both_classes():
    X = np.array([[0.0], [1.0]])
    with pytest.raises(ValueError, match="both filled"):
        fit_fill_model(X, [1, 1], ["ofi_1"])
