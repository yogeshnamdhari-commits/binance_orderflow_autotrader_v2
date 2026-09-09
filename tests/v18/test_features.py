import pytest

from app.v18.features import (
    LiquidationEvent,
    compute_cross_market_features,
    compute_funding_basis_features,
    compute_liquidation_features,
)


def test_liquidation_features_ignore_future_events():
    events = [
        LiquidationEvent(100, "BUY", 2.0, 100.0),
        LiquidationEvent(150, "SELL", 1.0, 100.0),
        LiquidationEvent(300, "SELL", 100.0, 100.0),
    ]
    result = compute_liquidation_features(events, now_ns=200, windows_ns=[100])
    assert result["liq_intensity_100"] > 0
    assert result["liq_signed_100"] > 0


def test_funding_and_basis_features_are_explicit_about_missing_data():
    result = compute_funding_basis_features(None, None, None)
    assert result["funding_missing"] == 1.0
    assert result["premium_missing"] == 1.0


def test_cross_market_features_use_lagged_returns():
    result = compute_cross_market_features(101.0, 100.0, 0.01, 0.02)
    assert result["cross_market_confirmation"] == pytest.approx(0.015)
    assert result["cross_market_divergence"] == pytest.approx(-0.01)
    assert result["target_reference_basis"] == pytest.approx(0.01)
