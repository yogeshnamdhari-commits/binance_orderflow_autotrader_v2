import numpy as np
import pandas as pd

from scripts.v21_orderflow_dataset import FEATURES
from scripts.v21_orderflow_models import _evaluate_fold
from scripts.v21_toxicity_model import _fit_eval


def _frame(n: int = 300, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame(
        {f: rng.normal(size=n) for f in FEATURES}
    )
    frame["move_100ms"] = (frame["queue_imbalance"] + rng.normal(scale=0.5, size=n) > 0).astype(int)
    frame["direction_100ms"] = (frame["ofi_500ms"] + rng.normal(scale=0.5, size=n) > 0).astype(int)
    frame["timestamp_ms"] = np.arange(n)
    frame["session"] = "A"
    frame["half"] = 0
    return frame


def test_two_stage_model_evaluation_returns_metrics():
    frame = _frame()
    train = frame.iloc[:220].copy()
    test = frame.iloc[220:].copy()
    result = _evaluate_fold(train, test, 100)
    assert result["status"] == "OK"
    assert result["stage1"]["auc"] is not None


def test_toxicity_model_evaluation_returns_metrics():
    rng = np.random.default_rng(8)
    frame = pd.DataFrame({f: rng.normal(size=160) for f in FEATURES})
    frame["toxic"] = (frame["queue_imbalance"] > 0).astype(int)
    frame["adverse_bps_100ms"] = frame["toxic"] * 0.1
    result = _fit_eval(frame.iloc[:120], frame.iloc[120:])
    assert result["status"] == "OK"
    assert 0.0 <= result["auc"] <= 1.0
