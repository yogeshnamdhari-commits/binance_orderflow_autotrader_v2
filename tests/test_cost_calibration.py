import json
from pathlib import Path
import numpy as np

from app.cost_sampler import walk_slippage_bps


def test_walk_slippage_no_crossing_rounds_to_zero():
    mid = 50000.0
    ask = [(50000.1, 10.0)]
    slip = walk_slippage_bps(ask, mid, 1000)
    assert slip is not None
    assert 0.01 < slip < 0.03


def test_walk_slippage_crosses_levels():
    mid = 100.0
    asks = [(100.1, 0.5), (100.2, 0.5), (100.3, 0.5)]
    slip = walk_slippage_bps(asks, mid, 100)
    assert slip is not None and slip > 0.1


def test_walk_slippage_insufficient_depth_returns_none():
    mid = 100.0
    asks = [(100.1, 0.1)]
    assert walk_slippage_bps(asks, mid, 1000) is None


def test_walk_slippage_empty_returns_none():
    assert walk_slippage_bps([], 100.0, 100) is None


def test_sampler_row_roundtrip(tmp_path):
    from app.cost_calibrate import summarize
    row = {
        "ts_ms": 1000, "bid": 99.9, "ask": 100.1, "mid": 100.0,
        "spread_bps": 2.0, "bb_qty": 5.0, "ba_qty": 5.0,
        "bid_depth5": 10.0, "ask_depth5": 10.0, "imb5": 0.0,
        "slip_buy1000": 0.1, "slip_sell1000": 0.1,
    }
    p = tmp_path / "s.jsonl"
    p.write_text(json.dumps(row) + "\n")
    s = summarize(p, out_dir=tmp_path)
    assert s["n_samples"] == 1
    assert "maker" in s
    assert (tmp_path / "cost_calibration.md").exists()


def test_calibrator_taker_rt_uses_fees():
    from app.cost_calibrate import _roundtrip_effective
    row = {"slip_buy1000": 0.5, "slip_sell1000": -0.5}
    assert _roundtrip_effective(row, 2.0, 1000) == 5.0
    assert _roundtrip_effective({"slip_buy1000": None, "slip_sell1000": -0.5}, 2.0, 1000) is None