import numpy as np
import pytest

from app.v18.models import expected_net_pnl, fit_fill_model, fit_return_model


def test_return_model_is_fit_on_supplied_training_data():
    X = np.array([[0.0], [1.0], [2.0], [3.0]])
    y = np.array([0.0, 1.0, 2.0, 3.0])
    model = fit_return_model(X, y, ["x"])
    assert model.predict(np.array([[4.0]])).shape == (1,)


def test_fill_model_requires_both_classes():
    X = np.array([[0.0], [1.0], [2.0]])
    with pytest.raises(ValueError, match="both filled and unfilled"):
        fit_fill_model(X, [1, 1, 1], ["x"])


def test_expected_net_pnl_reconciles_fill_and_non_fill_paths():
    value = expected_net_pnl(
        predicted_return=5.0,
        fill_probability=0.8,
        maker_round_trip_cost=1.0,
        taker_round_trip_cost=2.0,
        non_fill_opportunity_cost=0.5,
        maker_share=1.0,
    )
    assert value == pytest.approx(3.1)
