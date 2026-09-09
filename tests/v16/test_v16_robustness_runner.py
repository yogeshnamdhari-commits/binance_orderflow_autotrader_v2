"""Tests for deterministic V16 robustness evidence construction."""
from __future__ import annotations

import pandas as pd

from app.v16.robustness_runner import _market_state


def test_market_state_uses_fixed_median_partitions():
    row = pd.Series({"vol_regime": 2.0, "liquidity_state": 0.5, "spread_bps": 1.0})
    assert _market_state(row, 1.0, 1.0, 1.0) == "high_vol|low_liq|tight_spread"
