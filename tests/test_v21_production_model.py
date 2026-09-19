import hashlib
import json

import numpy as np

from app.research.v21_production_model import V21ModelBundle
from scripts.v21_orderflow_dataset import FEATURES


def make_payload():
    n = len(FEATURES)
    base = {
        "schema_version": 1,
        "model_family": "test",
        "horizon_ms": 250,
        "features": list(FEATURES),
        "training_sessions": ["A"],
        "training_sizes": {"rows": 1000},
        "dataset_sha256": "0" * 64,
        "toxicity_dataset_sha256": "1" * 64,
        "move": {"mean": [0.0] * n, "scale": [1.0] * n, "coef": [0.0] * n, "intercept": 0.0},
        "direction": {"mean": [0.0] * n, "scale": [1.0] * n, "coef": [0.0] * n, "intercept": 0.0},
        "magnitude": {"coef": [0.0] * n, "intercept": 1.5},
        "toxicity_buy": {"coef": [0.0] * n, "intercept": 0.25},
        "toxicity_sell": {"coef": [0.0] * n, "intercept": 0.50},
        "production_inference": {"training_in_live_process": False, "feature_order_locked": True},
    }
    raw = json.dumps(base, sort_keys=True, separators=(",", ":")).encode()
    base["bundle_sha256"] = hashlib.sha256(raw).hexdigest()
    return base


def test_frozen_bundle_hash_and_prediction():
    payload = make_payload()
    import pathlib
    path = pathlib.Path("/tmp/v21-test-bundle.json")
    path.write_text(json.dumps(payload), encoding="utf-8")
    model = V21ModelBundle.from_file(path)

    pred = model.predict(np.zeros(len(FEATURES)))
    assert pred.p_move == 0.5
    assert pred.p_up == 0.5
    assert pred.abs_move_bps == 1.5
    assert pred.expected_signed_move_bps == 0.0
    assert pred.toxicity_buy_bps == 0.25
    assert pred.toxicity_sell_bps == 0.50


def test_bundle_rejects_wrong_feature_order():
    payload = make_payload()
    payload["features"] = list(reversed(FEATURES))
    try:
        V21ModelBundle(payload)
    except ValueError as exc:
        assert str(exc) == "v21_feature_order_mismatch"
    else:
        raise AssertionError("feature order mismatch was accepted")
