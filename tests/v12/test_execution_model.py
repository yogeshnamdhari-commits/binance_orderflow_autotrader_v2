"""Tests for V12 execution model — funding-aware cost decomposition."""
import pytest

from app.v12.config import V12Config
from app.v12.execution_model import V12ExecutionModel, V12ExecutionConfig


def test_execution_model_accepts_v12_config():
    cfg = V12Config()
    em = V12ExecutionModel(config=cfg)
    assert em._cfg.holding_hours == cfg.max_holding_hours


def test_execution_model_accepts_execution_config():
    ec = V12ExecutionConfig(holding_hours=4.0)
    em = V12ExecutionModel(config=ec)
    assert em._cfg.holding_hours == 4.0


def test_funding_uses_8h_window_semantics():
    """Binance positive rate = longs pay. Long with +rate pays funding."""
    em = V12ExecutionModel(config=V12Config())
    # +0.01% per 8h rate, 8h hold, long edge (confidence 1.0)
    result = em.decompose_trade(
        signal_edge_bps=10.0, funding_rate_8h=0.0001,
        hold_duration_hours=8.0, signal_confidence=1.0, spread_bps=0.013,
    )
    # 0.0001 -> 1.0 bps per 8h, 1 period; long pays -> -1.0 bps
    assert result.funding_income_bps == -1.0


def test_funding_income_sign_for_short_edge():
    """Short with positive rate RECEIVES funding (longs pay shorts)."""
    em = V12ExecutionModel(config=V12Config())
    result = em.decompose_trade(
        signal_edge_bps=-10.0, funding_rate_8h=0.0001,
        hold_duration_hours=8.0, signal_confidence=1.0, spread_bps=0.013,
    )
    assert result.funding_income_bps == 1.0


def test_funding_scales_with_hold_duration():
    em = V12ExecutionModel(config=V12Config())
    r_8h = em.decompose_trade(
        signal_edge_bps=10.0, funding_rate_8h=0.0001,
        hold_duration_hours=8.0, signal_confidence=1.0,
    )
    r_16h = em.decompose_trade(
        signal_edge_bps=10.0, funding_rate_8h=0.0001,
        hold_duration_hours=16.0, signal_confidence=1.0,
    )
    # double the hold -> double the (negative) funding for a long
    assert r_16h.funding_income_bps == pytest.approx(2 * r_8h.funding_income_bps)


def test_net_ev_subtracts_all_costs():
    em = V12ExecutionModel(config=V12Config())
    result = em.decompose_trade(
        signal_edge_bps=10.0, funding_rate_8h=0.0,
        hold_duration_hours=8.0, signal_confidence=1.0, spread_bps=0.013,
    )
    # gross = 10.0, costs = entry(5+0.5+0.5+0.1) + exit(5+0.5+0.5+0.1) + spread(0.013)
    expected_cost = (5.0 + 0.5 + 0.5 + 0.1) * 2 + 0.013
    assert result.total_cost_bps == expected_cost
    assert result.gross_ev_bps == 10.0
    assert abs(result.net_ev_bps - (10.0 - expected_cost)) < 1e-9


def test_breakeven_funding_is_finite_and_positive_for_small_edge():
    em = V12ExecutionModel(config=V12Config())
    be = em.breakeven_funding_bps(signal_edge_bps=1.0, confidence=1.0, hold_duration_hours=8.0)
    assert be == be  # not NaN/inf
    assert be > 0
