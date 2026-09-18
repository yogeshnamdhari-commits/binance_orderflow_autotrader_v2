import json

import pytest

from app.v19.config import load_v19_config


def _payload(**overrides):
    payload = {
        "symbol": "BTCUSDT",
        "prediction_horizon_ms": 2000,
        "feature_names": ["ofi_1"],
        "min_train_events": 100,
        "min_test_events": 50,
        "embargo_events": 2,
        "max_feature_age_ms": 1000,
        "maker_round_trip_cost_bps": 1.0,
        "taker_round_trip_cost_bps": 2.0,
        "non_fill_opportunity_cost_bps": 0.5,
        "maker_share": 1.0,
        "cost_stress_multipliers": [1.0, 1.25],
        "live_order_submission": False,
    }
    payload.update(overrides)
    return payload


def test_v19_rejects_live_submission(tmp_path):
    path = tmp_path / "v19.json"
    path.write_text(json.dumps(_payload(live_order_submission=True)))
    with pytest.raises(ValueError, match="live order submission"):
        load_v19_config(path)


def test_v19_rejects_unknown_feature(tmp_path):
    path = tmp_path / "v19.json"
    path.write_text(json.dumps(_payload(feature_names=["future_signal"])))
    with pytest.raises(ValueError, match="unknown V19 feature"):
        load_v19_config(path)
