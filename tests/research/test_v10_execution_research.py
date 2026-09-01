import numpy as np
import pandas as pd
from app.v10_execution_research import build_execution_observations, summarize_execution_economics


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
