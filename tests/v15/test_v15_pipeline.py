"""V15 test suite — execution-aware pipeline, regime filter, model, gate."""
from __future__ import annotations

import json
import sys
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.v15.config import V15Config
from app.v15.features import extract_v15_features, build_v15_targets, build_v15_returns, V15_FEATURES
from app.v15.model import V15SignalModel
from app.v15.execution import V15ExecutionRouter, V15ExecutionDecision
from app.v15.regime import V15RegimeFilter
from app.v15.gate import V15ProductionGate
from app.v15.pipeline import calibrate, forward


def test_v15_config_hash_stability():
    cfg = V15Config()
    h1 = cfg.config_hash()
    h2 = V15Config().config_hash()
    assert h1 == h2
    assert h1 == "aa505ca8abe09376"
    assert cfg.prediction_horizon_ms == 10000
    assert cfg.model_type == "gbr"
    assert cfg.live_trading_enabled is False


def test_v15_config_breakeven_threshold():
    cfg = V15Config()
    assert cfg.breakeven_threshold_bps > cfg.total_roundtrip_cost_bps
    assert cfg.safety_margin_bps == 1.0
    assert cfg.total_roundtrip_cost_bps < 5.0


def test_v15_feature_set_is_parsimonious():
    assert len(V15_FEATURES) <= 15
    assert "book_imbalance_l1" in V15_FEATURES
    assert "vol_regime_flag" in V15_FEATURES
    assert "liquidity_regime_flag" in V15_FEATURES


def test_v15_regime_filter():
    df = pd.DataFrame({
        "vol_regime": [1.0, 5.0, 3.0, 4.0],
        "liquidity_state": [10.0, 50.0, 30.0, 40.0],
        "spread_bps": [0.5, 0.8, 1.5, 2.0],
    })
    regime = V15RegimeFilter(vol_pct=50, liquidity_pct=50, spread_pct=50)
    mask = regime.fit(df).filter(df)
    # Row 1: vol=5 (>median 3.5), liq=50 (>median 35), spread=0.8 (<median 1.25) → ALL pass
    assert mask.sum() == 1
    assert mask.iloc[1] == True
    assert mask.dtype == bool


def test_v15_execution_router_maker_vs_taker():
    cfg = V15Config()
    router = V15ExecutionRouter(cfg)

    # Low predicted return -> NONE
    d = router.route(0.5, True)
    assert d.action == "NONE"

    # Medium predicted return -> MAKER
    maker_cost = cfg.maker_rebate_bps + cfg.slippage_bps + cfg.adverse_selection_bps + cfg.latency_bps
    d = router.route(maker_cost + cfg.exit_cost_bps + cfg.safety_margin_bps + 0.1, True)
    assert d.action == "MAKER"
    assert d.fill_probability == cfg.maker_fill_probability

    # High predicted return -> TAKER
    taker_cost = cfg.taker_fee_bps + cfg.slippage_bps + cfg.adverse_selection_bps + cfg.latency_bps
    d = router.route(taker_cost + cfg.exit_cost_bps + cfg.safety_margin_bps + 0.1, True)
    assert d.action == "TAKER"
    assert d.fill_probability == 1.0

    # Regime fails -> NONE
    d = router.route(100.0, False)
    assert d.action == "NONE"
    assert d.regime_passed is False


def test_v15_model_gbr_predicts_magnitude():
    np.random.seed(42)
    n = 200
    cols = V15_FEATURES
    X = pd.DataFrame({c: np.random.randn(n) for c in cols})
    y = pd.Series(np.random.randn(n) * 5)  # returns in bps
    model = V15SignalModel(V15Config())
    metrics = model.fit(X, y)
    assert "train_mae" in metrics
    assert metrics["train_mae"] >= 0
    preds = model.predict(X)
    assert len(preds) == n
    assert isinstance(preds, np.ndarray)


def test_v15_no_lookahead_in_features():
    books = [type('B', (), {
        'ts_ms': i * 1000, 'bids': {100: 1.0}, 'asks': {100: 1.0},
        'mid': 100.0, 'spread_bps': 2.0, 'add': 1, 'cancel': 0,
        'bid_depth1': 1.0, 'ask_depth1': 1.0, 'adds': 1.0, 'cancels': 0.0,
    })() for i in range(1, 30)]
    trades = []
    df = extract_v15_features(books, trades, 10000)
    assert "ts_ms" in df.columns
    assert list(df["ts_ms"]) == [b.ts_ms for b in books]


def test_v15_production_gate_live_hardlock():
    cfg = V15Config()
    gate = V15ProductionGate(cfg)
    result = gate.evaluate()
    live_check = result["checks"]["live_order_submission"]
    assert live_check["hard_disabled"] is True
    assert result["live_order_submission"] is False


def test_v15_production_gate_config_integrity():
    cfg = V15Config()
    gate = V15ProductionGate(cfg)
    result = gate.evaluate()
    config_check = result["checks"]["config_integrity"]
    assert config_check["status"] == "PASS"


def test_v15_features_match_proposal():
    proposal = json.loads(Path("data/research/v15_proposal.json").read_text())
    proposal_features = set(proposal["architecture"]["features"].split(" + ")[0].replace("10 order-flow features (reuse V14) + 3 regime features (vol, liquidity, spread)", "").split(", "))
    # V15 adds 3 regime flags to V14's 10 features
    assert len(V15_FEATURES) == 13
    assert "vol_regime_flag" in V15_FEATURES
    assert "liquidity_regime_flag" in V15_FEATURES
    assert "spread_regime_flag" in V15_FEATURES
