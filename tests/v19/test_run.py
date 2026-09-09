import json

import numpy as np

from app.v19.config import V19Config
from app.v19.pipeline import run_forward_pipeline, write_evidence


def test_pipeline_writes_locked_evidence(tmp_path):
    config = V19Config(
        symbol="BTCUSDT", prediction_horizon_ms=2000,
        feature_names=("queue_imbalance_1",), min_train_events=4,
        min_test_events=2, embargo_events=1, max_feature_age_ms=1000,
        maker_round_trip_cost_bps=1.0, taker_round_trip_cost_bps=2.0,
        non_fill_opportunity_cost_bps=0.5, maker_share=1.0,
        cost_stress_multipliers=(1.0, 1.25), live_order_submission=False,
        config_hash="test",
    )
    X = np.arange(12, dtype=float).reshape(-1, 1)
    returns = np.linspace(1.0, 3.0, 12)
    fills = np.array([0, 1] * 6)
    ts = np.arange(12) * 1_000_000_000
    result = run_forward_pipeline(X, returns, fills, ts, config, v16_outcomes=np.linspace(0.9, 1.0, 4))
    path = tmp_path / "evidence.json"
    write_evidence(result, path)
    saved = json.loads(path.read_text())
    assert saved["live_order_submission"] is False
    assert "net_ev_bps" in saved
