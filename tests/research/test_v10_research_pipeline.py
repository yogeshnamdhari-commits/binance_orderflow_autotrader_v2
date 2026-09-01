import pandas as pd
import pytest
from app.v10_research_pipeline import run_walkforward


def _data(n=12):
    idx = pd.date_range("2026-01-01", periods=n, freq="s", tz="UTC")
    return pd.DataFrame({
        "queue_ahead": [0.0, 1.0] * (n // 2),
        "filled": [1, 0] * (n // 2),
        "time_to_fill": [1.0, 2.0] * (n // 2),
        "adverse_selection_bps": [1.0, 2.0] * (n // 2),
        "fill_fraction": [1.0, 0.0] * (n // 2),
    }, index=idx)


def test_pipeline_returns_chronological_oos_folds():
    result = run_walkforward(
        _data(), train_size=4, embargo=1, test_size=2, step=2,
        bins=[0.0, 1.0, 2.0], survival_horizon=2.0,
        spread_capture_bps=4.0, fee_rebate_bps=0.0,
        inventory_cost_bps=0.0, exit_cost_bps=0.5,
        cancellation_cost_bps=0.1,
    )
    assert len(result) == 4
    for fold in result:
        assert fold["train_end"] < fold["oos_start"]
        assert fold["oos_orders"] == 2


def test_pipeline_rejects_non_datetime_index():
    with pytest.raises(ValueError, match="DatetimeIndex"):
        run_walkforward(_data().reset_index(drop=True), train_size=4, embargo=1, test_size=2, step=2,
                        bins=[0.0, 1.0, 2.0], survival_horizon=2.0,
                        spread_capture_bps=4.0, fee_rebate_bps=0.0,
                        inventory_cost_bps=0.0, exit_cost_bps=0.5,
                        cancellation_cost_bps=0.1)
