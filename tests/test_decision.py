"""Tests for the production decision engine (app.decision)."""
import pytest
import numpy as np
import pandas as pd
from app.features import FlowFeatures, V5_FEATURES
from app.decision import DecisionEngine, DecisionState
from app.fillmodel import PassiveFillModel
from app.v5_calibration import calibrate_prediction


def _feat_v5(**kw):
    """Create FlowFeatures with V5 features."""
    base = dict(
        mid=100.0, spread_bps=1.0,
        book_state="BOOK_VALID", liquidity_state="NORMAL",
        toxicity_state="LOW_TOXICITY",
        # V5 features (all zeros by default)
        ofi_l1=0.0, ofi_norm_l1=0.0, qi_l1=0.0, di_l5=0.0, di_l10=0.0,
        mpd_bps=0.0, bid_cancel_bps=0.0, ask_add_bps=0.0,
        cancel_pressure=0.0, tfi_500=0.0, liq_depletion=0.0,
        log_depth1=0.0, log_depth5=0.0, log_event_rate=0.0,
        depth_slope_bps=0.0, vol_500=0.0,
    )
    base.update(kw)
    return FlowFeatures(**base)


def _make_test_engine(calibrated_value=1.0):
    """Create a DecisionEngine with mocked calibration returning fixed value."""
    return DecisionEngine(
        _calibrate_fn=lambda model_d, df, horizon_ms, calibration: np.array([1.0])
    )


def test_invalid_data_blocks():
    f = _feat_v5(book_state="BOOK_INVALID")
    d = DecisionEngine(_predict_fn=lambda df: np.array([1.0])).evaluate(f)
    assert d.state == DecisionState.INVALID_DATA


def test_no_signal_when_calibrated_zero():
    f = _feat_v5()
    d = DecisionEngine(_calibrate_fn=lambda m, df, h, c: np.array([0.0])).evaluate(f)
    assert d.state == DecisionState.NO_SIGNAL


def test_insufficient_liquidity_blocks():
    f = _feat_v5(liquidity_state="THIN")
    d = DecisionEngine(_calibrate_fn=lambda m, df, h, c: np.array([5.0])).evaluate(f)
    assert d.state == DecisionState.INSUFFICIENT_LIQUIDITY


def test_high_toxicity_blocks():
    f = _feat_v5(toxicity_state="HIGH_TOXICITY")
    d = DecisionEngine(_calibrate_fn=lambda m, df, h, c: np.array([5.0])).evaluate(f)
    assert d.state == DecisionState.HIGH_TOXICITY


def test_cost_overwhelmed_without_edge():
    # valid signal but gross <= 0
    f = _feat_v5()
    d = DecisionEngine(_calibrate_fn=lambda m, df, h, c: np.array([-1.0])).evaluate(f)
    assert d.state == DecisionState.COST_OVERWHELMED
    assert d.gross_bps <= 0


def test_execution_ready_with_positive_edge():
    f = _feat_v5()
    d = DecisionEngine(_calibrate_fn=lambda m, df, h, c: np.array([10.0])).evaluate(f)
    assert d.state == DecisionState.EXECUTION_READY
    assert d.side == "BUY"
    assert d.gross_bps > 0
    assert d.net_bps > 0