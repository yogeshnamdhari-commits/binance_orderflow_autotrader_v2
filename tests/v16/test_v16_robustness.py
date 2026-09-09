"""V16 robustness tests — pre-registered stress and stability checks."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.v16.robustness import evaluate_robustness


def _trades(n: int = 120, mean: float = 2.0) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    returns = rng.normal(mean, 0.8, n)
    return pd.DataFrame({
        "predicted_return_bps": returns + 1.0,
        "fill_probability": np.full(n, 0.8),
        "total_cost_bps": np.full(n, 1.7),
        "expected_pnl_bps": returns,
        "regime": np.array(["A", "B", "C", "D", "E", "F"] * (n // 6)),
    })


def test_robustness_passes_stable_positive_trade_set():
    result = evaluate_robustness(_trades())
    assert result["status"] == "PASS"
    assert result["checks"]["chronological_blocks"]["positive_blocks"] >= 4
    assert result["checks"]["cost_stress"]["worst_case_net_ev_bps"] > 0
    assert result["checks"]["leave_one_regime_out"]["positive_regimes"] >= 4


def test_robustness_fails_when_cost_stress_erases_edge():
    result = evaluate_robustness(_trades(mean=0.2))
    assert result["status"] == "FAIL"
    assert result["checks"]["cost_stress"]["worst_case_net_ev_bps"] <= 0


def test_robustness_rejects_insufficient_samples():
    result = evaluate_robustness(_trades(30))
    assert result["status"] == "BLOCKED"
