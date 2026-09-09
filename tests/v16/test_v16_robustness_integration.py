"""Integration tests for producing V16 robustness evidence from forward trades."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.v16.pipeline import _build_trade_robustness_frame


def test_build_trade_robustness_frame_uses_only_selected_trades():
    feats = pd.DataFrame({
        "predicted_return_bps": [2.0, -3.0, 4.0],
        "fill_probability": [0.8, 0.9, 0.7],
        "total_cost_bps": [1.5, 1.5, 1.5],
        "volatility_regime_flag": [0.0, 1.0, 1.0],
        "liquidity_regime_flag": [1.0, 0.0, 1.0],
        "spread_regime_flag": [1.0, 1.0, 0.0],
    })
    decisions = [
        type("D", (), {"action": "MAKER", "predicted_return_bps": 2.0, "fill_probability": 0.8,
                       "total_cost_bps": 1.5, "expected_pnl_bps": 0.1})(),
        type("D", (), {"action": "NONE", "predicted_return_bps": -3.0, "fill_probability": 0.9,
                       "total_cost_bps": 1.5, "expected_pnl_bps": -4.2})(),
        type("D", (), {"action": "TAKER", "predicted_return_bps": 4.0, "fill_probability": 0.7,
                       "total_cost_bps": 1.5, "expected_pnl_bps": 1.3})(),
    ]

    out = _build_trade_robustness_frame(feats, decisions)
    assert len(out) == 2
    assert out["expected_pnl_bps"].tolist() == [0.1, 1.3]
    assert out["regime"].tolist() == ["011", "110"]
