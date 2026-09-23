"""Tests for V12 pipeline end-to-end on real captured sessions.

Uses the existing calibration/forward sessions under data/v12/ (real Binance data).
The pipeline must run without errors and produce an honest FAIL result because
the V12 signal has no statistically significant predictive power on BTCUSDT.
"""
import json
from pathlib import Path

from app.v12.config import V12Config
from app.v12.pipeline import run_v12_calibration, run_v12_forward, parse_session


def _cal_dirs():
    d = Path("data/v12/calibration")
    return sorted([x for x in d.iterdir() if x.is_dir()]) if d.exists() else []


def _fwd_dirs():
    d = Path("data/v12/forward")
    return sorted([x for x in d.iterdir() if x.is_dir()]) if d.exists() else []


def test_parse_session_returns_books_and_trades():
    dirs = _cal_dirs()
    if not dirs:
        import pytest
        pytest.skip("no calibration sessions available")
    books, trades = parse_session(dirs[0])
    assert isinstance(books, list)
    assert isinstance(trades, list)
    assert len(books) > 0


def test_pipeline_calibration_produces_frozen_model(tmp_path):
    dirs = _cal_dirs()
    if not dirs:
        import pytest
        pytest.skip("no calibration sessions available")
    config = V12Config()
    result = run_v12_calibration(dirs, tmp_path, config)
    assert result["calibration_artifact"]["status"] == "CALIBRATED"
    assert (tmp_path / "v12_frozen_model.joblib").exists()
    assert "model_checksum" in result


def test_pipeline_forward_result_is_honest_fail(tmp_path):
    """On real data the V12 signal fails every gate — this is the EXPECTED outcome."""
    cal_dirs = _cal_dirs()
    fwd_dirs = _fwd_dirs()
    import pytest
    if not cal_dirs or not fwd_dirs:
        pytest.skip("calibration or forward sessions unavailable")
    config = V12Config()
    run_v12_calibration(cal_dirs, tmp_path, config)
    model_path = tmp_path / "v12_frozen_model.joblib"
    fwd = run_v12_forward(fwd_dirs, model_path, tmp_path, config)
    # The frozen model is evaluated against INDEPENDENT forward data.
    assert fwd["status"] == "FAIL"
    assert fwd["mean_net_ev_bps"] < 0
    assert fwd["gate_conditions"]["net_ev_positive"] is False
