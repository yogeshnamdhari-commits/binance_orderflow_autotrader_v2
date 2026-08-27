"""Tests for the production orchestrator governance + gate chain.

The live-trading hard block (V5_BASELINE_NO_LIVE_TRADE) must remain active
and must reject any decision before any strategy/fill/risk evaluation.
"""
from app.orchestrator import TradeOrchestrator
from app.config import V5_BASELINE_NO_LIVE_TRADE


def test_governance_hard_block_active():
    assert V5_BASELINE_NO_LIVE_TRADE is True
    orch = TradeOrchestrator()
    r = orch.decide("delta_5s_top_decile", notional_usd=10_000,  # notional but gov blocks first
                    book=None, equity=100_000, daily_pnl_pct=0.0, spread_bps=1.0)
    assert r["allowed"] is False
    assert "NO LIVE TRADING" in r["reason"]
    assert r["governance"]["blocked"] is True


def test_runtime_safe_blocks_live_when_governance_set():
    from app.config import Config
    cfg = Config()
    ok, reason = cfg.runtime_safe()
    # mode defaults to 'paper'; runtime_safe only blocks 'live' + governance lock
    if cfg.mode == "live":
        assert ok is False
    else:
        assert ok is True
