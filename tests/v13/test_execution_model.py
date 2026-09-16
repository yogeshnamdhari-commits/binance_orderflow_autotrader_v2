"""Tests for V13 execution model — funding semantics at 2s horizon."""
import pytest

from app.v13.config import V13Config
from app.v12.execution_model import V12ExecutionModel, V12ExecutionConfig


def test_v13_config_horizon_is_2seconds():
    assert V13Config.prediction_horizon_ms == 2000
    assert V13Config.feature_window_ms == 2000


def test_v13_config_hash_stable():
    assert V13Config.config_hash() == V13Config.config_hash()


def test_v13_config_hash_differs_from_v12():
    from app.v12.config import V12Config
    assert V13Config.config_hash() != V12Config.config_hash()


def test_v13_exec_model_long_pays_funding_when_rate_positive():
    ec = V12ExecutionConfig(
        taker_fee_bps=V13Config.taker_fee_bps, slippage_bps=V13Config.slippage_bps,
        adverse_selection_bps=V13Config.adverse_selection_bps, latency_bps=V13Config.latency_bps,
        exit_cost_bps=V13Config.exit_cost_bps,
    )
    em = V12ExecutionModel(config=ec)
    r = em.decompose_trade(
        signal_edge_bps=10.0, funding_rate_8h=0.0001,
        hold_duration_hours=1.0, signal_confidence=1.0, spread_bps=0.013,
    )
    # 1 hour = 1/8 of 8h period; 0.0001 -> 1.0 bps per 8h -> 0.125 bps for long
    # Long pays positive rate -> negative funding income
    assert r.funding_income_bps == pytest.approx(-0.125, abs=1e-9)


def test_v13_exec_model_short_receives_funding_when_rate_positive():
    ec = V12ExecutionConfig(
        taker_fee_bps=V13Config.taker_fee_bps, slippage_bps=V13Config.slippage_bps,
        adverse_selection_bps=V13Config.adverse_selection_bps, latency_bps=V13Config.latency_bps,
        exit_cost_bps=V13Config.exit_cost_bps,
    )
    em = V12ExecutionModel(config=ec)
    r = em.decompose_trade(
        signal_edge_bps=-10.0, funding_rate_8h=0.0001,
        hold_duration_hours=1.0, signal_confidence=1.0, spread_bps=0.013,
    )
    # Short receives positive rate -> +0.125 bps
    assert r.funding_income_bps == pytest.approx(0.125, abs=1e-9)
