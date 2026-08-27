"""Tests for V5 governance enforcement."""
import json
from pathlib import Path

import pytest

from app.config import V5_BASELINE_NO_LIVE_TRADE
from app.orchestrator import TradeOrchestrator


def test_v5_baseline_no_live_trade_constant_is_true():
    assert V5_BASELINE_NO_LIVE_TRADE is True


def test_orchestrator_governance_blocks_all_decisions():
    orch = TradeOrchestrator()
    # Any condition should be blocked by governance
    result = orch.decide("delta_5s_top_decile")
    assert result["allowed"] is False
    assert "NO LIVE TRADING" in result["reason"]
    assert result["governance"]["blocked"] is True
    assert result["governance"]["rule"] == "V5_BASELINE_NO_LIVE_TRADE"


def test_orchestrator_governance_blocks_even_when_book_and_equity_provided():
    orch = TradeOrchestrator()
    result = orch.decide("delta_5s_bottom_decile", notional_usd=10_000,
                         equity=100_000, spread_bps=1.0)
    assert result["allowed"] is False
    assert "NO LIVE TRADING" in result["reason"]


def test_orchestrator_governance_blocks_unknown_condition():
    orch = TradeOrchestrator()
    result = orch.decide("unknown_condition")
    assert result["allowed"] is False
    assert "NO LIVE TRADING" in result["reason"]


def test_config_assert_safe_allows_paper_mode():
    from app.config import Config
    cfg = Config(mode="paper", live_trading_enabled=False)
    # Should not raise
    cfg.assert_safe()


def test_config_assert_safe_blocks_live_mode_when_disabled():
    from app.config import Config
    with pytest.raises(RuntimeError, match="LIVE_TRADING_ENABLED=false"):
        cfg = Config(mode="live", live_trading_enabled=False)
        cfg.assert_safe()
