import json

import pytest

from app.v18.config import load_v18_config


def _write(tmp_path, payload):
    path = tmp_path / "v18.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_config_rejects_live_submission(tmp_path):
    payload = {
        "symbol": "BTCUSDT",
        "prediction_horizon_ms": 10000,
        "feature_families": ["v16_control"],
        "min_train_events": 1,
        "min_test_events": 1,
        "max_feature_age_ms": 100,
        "cost_stress_multipliers": [1.0],
        "live_order_submission": True,
    }
    with pytest.raises(ValueError, match="live order submission"):
        load_v18_config(_write(tmp_path, payload))


def test_config_rejects_unknown_feature_family(tmp_path):
    payload = {
        "symbol": "BTCUSDT",
        "prediction_horizon_ms": 10000,
        "feature_families": ["invented_alpha"],
        "min_train_events": 1,
        "min_test_events": 1,
        "max_feature_age_ms": 100,
        "cost_stress_multipliers": [1.0],
        "live_order_submission": False,
    }
    with pytest.raises(ValueError, match="unknown V18 feature families"):
        load_v18_config(_write(tmp_path, payload))


def test_valid_config_gets_deterministic_hash(tmp_path):
    payload = {
        "symbol": "BTCUSDT",
        "prediction_horizon_ms": 10000,
        "feature_families": ["v16_control", "liquidation"],
        "min_train_events": 10,
        "min_test_events": 5,
        "max_feature_age_ms": 100,
        "cost_stress_multipliers": [1.0, 1.25],
        "live_order_submission": False,
    }
    config = load_v18_config(_write(tmp_path, payload))
    assert len(config.config_hash) == 64
    assert config.live_order_submission is False
