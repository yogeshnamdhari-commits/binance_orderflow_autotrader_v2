import numpy as np
import pandas as pd
from app.v10_execution_research import (
    build_execution_observations,
    summarize_execution_economics,
    evaluate_execution_fold,
)


def test_build_execution_observations_aligns_fill_and_future_mid_without_leakage():
    events = pd.DataFrame({
        "timestamp": pd.to_datetime(["2026-01-01 00:00:00", "2026-01-01 00:00:01", "2026-01-01 00:00:02"]),
        "mid": [100.0, 100.1, 99.9],
        "side": ["bid", "bid", "ask"],
        "fill_fraction": [1.0, 0.0, 1.0],
        "queue_ahead": [2.0, 4.0, 1.0],
    })
    out = build_execution_observations(events, horizon=1)
    assert len(out) == 2
    assert out.iloc[0]["post_mid"] == 100.1
    assert out.iloc[0]["adverse_selection_bps"] < 0
    assert out.iloc[1]["adverse_selection_bps"] > 0


def test_summary_returns_explicit_fill_and_adverse_selection_metrics():
    obs = pd.DataFrame({
        "fill_fraction": [1.0, 0.0, 0.5, 1.0],
        "adverse_selection_bps": [1.0, 0.0, 2.0, -1.0],
        "queue_ahead": [1.0, 2.0, 3.0, 1.0],
    })
    result = summarize_execution_economics(obs)
    assert result["orders"] == 4
    assert result["filled_orders"] == 3
    assert result["fill_rate"] == 0.75
    assert np.isfinite(result["mean_adverse_selection_bps"])


def test_execution_fold_keeps_ex_ante_expected_ev_separate_from_realized_ev():
    train = pd.DataFrame({
        "queue_ahead": [0.0, 0.0, 1.0, 1.0],
        "filled": [1, 1, 0, 0],
        "time_to_fill": [1.0, 2.0, 2.0, 3.0],
        "adverse_selection_bps": [1.0, 3.0, 0.0, 0.0],
    })
    test = pd.DataFrame({
        "queue_ahead": [0.0, 1.0],
        "filled": [1, 0],
        "time_to_fill": [1.0, 3.0],
        "adverse_selection_bps": [2.0, 4.0],
        "fill_fraction": [1.0, 0.0],
    })
    result = evaluate_execution_fold(
        train, test, bins=[0.0, 1.0, 2.0], survival_horizon=2.0,
        spread_capture_bps=4.0, fee_rebate_bps=0.0,
        inventory_cost_bps=0.0, exit_cost_bps=0.5,
        cancellation_cost_bps=0.1,
    )
    assert result["oos_orders"] == 2
    assert result["mean_predicted_fill_probability"] == 0.25
    assert result["predicted_horizon_fill_probability"] == 0.5
    assert result["mean_predicted_adverse_selection_bps"] == 1.0
    assert np.isclose(result["mean_oos_expected_ev_bps"], 0.275)
    assert np.isclose(result["mean_oos_realized_ev_bps"], 0.65)
