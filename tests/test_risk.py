"""Tests for the production risk engine (app.risk)."""
import pytest
from app.risk import RiskEngine


def test_size_inverse_fractional():
    r = RiskEngine()
    d = r.size(100_000, entry=100.0, stop=95.0, daily_pnl_pct=0.0, spread_bps=1.0)
    assert d.allowed
    # qty = equity * risk_per_trade / |entry - stop|
    assert d.qty == pytest.approx(100_000 * 0.0025 / 5.0)


def test_spread_too_wide_blocks():
    r = RiskEngine()
    d = r.size(100_000, entry=100.0, stop=95.0, spread_bps=10.0)
    assert not d.allowed
    assert "spread" in d.reason


def test_emergency_blocks_pretrade():
    r = RiskEngine()
    r.trigger_emergency("unit test")
    d = r.pre_trade(100_000, 100.0, 95.0, 1.0, 1_000_000, 1_000_000, True)
    assert not d.allowed
    assert "EMERGENCY" in d.reason


def test_stale_data_blocks():
    r = RiskEngine()
    now = 2_000_000
    stale = now - 10_000  # > stale_ms default 2000
    d = r.pre_trade(100_000, 100.0, 95.0, 1.0, stale, now, True)
    assert not d.allowed
    assert "stale" in d.reason.lower()


def test_disconnected_blocks():
    r = RiskEngine()
    d = r.pre_trade(100_000, 100.0, 95.0, 1.0, 2_000_000, 2_000_000, False)
    assert not d.allowed
    assert "disconnect" in d.reason.lower()


def test_drawdown_halt():
    r = RiskEngine(max_drawdown_bps=100.0)
    r.peak_equity = 100_000.0
    # equity dropped 2% => 200 bps > 100 limit
    d = r.pre_trade(98_000.0, 100.0, 95.0, 1.0, 2_000_000, 2_000_000, True)
    assert not d.allowed
    assert "drawdown" in d.reason.lower()


def test_rejection_cooldown():
    r = RiskEngine(max_rejections=3, rejection_cooldown_s=60)
    for _ in range(3):
        r.handle_rejection("o1", now_s=1_000.0)
    assert r.rejection_cooldown_active(1_010.0) is True
    # after cooldown elapses, resets
    assert r.rejection_cooldown_active(1_100.0) is False
