import pandas as pd
from app.v10_oos_economics import evaluate_oos_fold


def test_oos_fold_fits_fill_rate_on_train_and_evaluates_test_only():
    train = pd.DataFrame({"queue_ahead": [0, 0, 1, 1], "filled": [1, 1, 0, 0]})
    test = pd.DataFrame({
        "queue_ahead": [0, 1], "fill_fraction": [1.0, 0.0],
        "adverse_selection_bps": [0.5, 0.0],
    })
    result = evaluate_oos_fold(train, test, bins=[0, 1, 2], spread_capture_bps=4.0,
                                fee_rebate_bps=0.0, inventory_cost_bps=0.0,
                                exit_cost_bps=0.5, cancellation_cost_bps=0.1)
    assert result["oos_orders"] == 2
    assert result["train_fill_rate"] == 0.5
    assert result["oos_realized_fill_rate"] == 0.5
    assert result["mean_oos_ev_bps"] == 1.4
