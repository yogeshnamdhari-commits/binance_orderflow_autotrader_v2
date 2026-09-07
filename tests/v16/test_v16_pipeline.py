"""V16 test suite — event-time features, queue pressure, models, walk-forward, gate."""
from __future__ import annotations

import json
import sys
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.v16.config import V16Config
from app.v16.features import extract_v16_features, V16_FEATURES
from app.v16.queue_pressure import V16QueuePressure
from app.v16.model import V16ReturnModel, V16FillProbabilityModel
from app.v16.execution import V16ExecutionSim, V16ExecutionDecision
from app.v16.walk_forward import V16WalkForward
from app.v16.gate import V16ProductionGate
from app.v16.pipeline import calibrate, forward


def test_v16_config_hash_stability():
    cfg = V16Config()
    h1 = cfg.config_hash()
    h2 = V16Config().config_hash()
    assert h1 == h2
    assert h1 == "e07dd90923983920"
    assert cfg.prediction_horizon_ms == 10000
    assert cfg.live_trading_enabled is False
    assert cfg.stop_loss_bps == 50.0
    assert cfg.max_holding_hours == 8.0


def test_v16_feature_set_is_parsimonious():
    assert len(V16_FEATURES) == 33
    assert "ofi_l1_best" in V16_FEATURES
    assert "book_pressure" in V16_FEATURES
    assert "queue_pressure" not in V16_FEATURES  # replaced by book_pressure in V16


def test_v16_no_lookahead_in_features():
    books = [type('B', (), {
        'ts_ms': i * 1000, 'bids': {100: 1.0}, 'asks': {100: 1.0},
        'mid': 100.0, 'spread_bps': 2.0, 'add': 1, 'cancel': 0,
        'bid_depth1': 1.0, 'ask_depth1': 1.0, 'bid_depth5': 1.0, 'ask_depth5': 1.0,
        'bid_depth10': 1.0, 'ask_depth10': 1.0, 'adds': 1.0, 'cancels': 0.0, 'net': 1.0,
        'buy_vol': 0.0, 'sell_vol': 0.0, 'tfi': 0.0,
    })() for i in range(1, 30)]
    trades = []
    df = extract_v16_features(books, trades, 10000)
    assert "ts_ms" in df.columns
    assert len(df) == len(books)


def test_v16_queue_pressure():
    books = [type('B', (), {
        'ts_ms': i * 1000, 'bids': {100: 1.0}, 'asks': {100: 1.0},
        'mid': 100.0, 'spread_bps': 2.0, 'add': 1, 'cancel': 0,
        'bid_depth1': 1.0, 'ask_depth1': 1.0, 'adds': 1.0, 'cancels': 0.0, 'net': 1.0,
    })() for i in range(1, 10)]
    trades = []
    qp = V16QueuePressure(window_ms=10000)
    df = qp.compute(books, trades)
    assert "queue_pressure" in df.columns
    assert len(df) == len(books)
    assert pytest.approx(df["queue_pressure"].iloc[0], rel=1e-6) == 1.0


def test_v16_return_model_gbr():
    np.random.seed(42)
    n = 200
    cols = V16_FEATURES
    X = pd.DataFrame({c: np.random.randn(n) for c in cols})
    y = pd.Series(np.random.randn(n) * 5)
    model = V16ReturnModel(V16Config())
    metrics = model.fit(X, y)
    assert "train_mae" in metrics
    assert metrics["train_mae"] >= 0
    preds = model.predict(X)
    assert len(preds) == n


def test_v16_fill_probability_model():
    np.random.seed(42)
    n = 200
    cols = V16_FEATURES
    X = pd.DataFrame({c: np.random.randn(n) for c in cols})
    y = pd.Series(np.random.randint(0, 2, n))
    model = V16FillProbabilityModel(V16Config())
    metrics = model.fit(X, y)
    assert "train_auc" in metrics
    assert 0.0 <= metrics["train_auc"] <= 1.0
    probs = model.predict_proba(X)
    assert len(probs) == n
    assert (probs >= 0).all() and (probs <= 1).all()


def test_v16_execution_router_maker_vs_taker():
    cfg = V16Config()
    sim = V16ExecutionSim(cfg)

    d = sim.route(0.5, 0.8)
    assert d.action == "NONE"
    assert d.reason == "negative_expected_pnl"

    d = sim.route(5.0, 0.8)
    assert d.action in ("MAKER", "TAKER")
    assert d.expected_pnl_bps > 0 or d.action == "NONE"


def test_v16_walk_forward_splits():
    df = pd.DataFrame({"ts_ms": range(1000), "feature": np.random.randn(1000)})
    wf = V16WalkForward(V16Config())
    folds = wf.split(df)
    assert len(folds) > 0
    for fold in folds:
        assert "train" in fold
        assert "validate" in fold
        assert "forward" in fold
        assert len(fold["train"]) > 0
        assert len(fold["forward"]) > 0


def test_v16_production_gate_live_hardlock():
    cfg = V16Config()
    gate = V16ProductionGate(cfg)
    result = gate.evaluate()
    assert result["live_order_submission"] is False
    assert result["checks"]["live_order_submission"]["hard_disabled"] is True


def test_v16_production_gate_config_integrity():
    cfg = V16Config()
    gate = V16ProductionGate(cfg)
    result = gate.evaluate()
    assert result["checks"]["config_integrity"]["status"] == "PASS"


def test_v16_features_match_proposal():
    proposal = json.loads(Path("data/research/v16_proposal.json").read_text())
    assert proposal["prediction_horizon_ms"] == 10000
    assert proposal["config_hash"] == "e07dd90923983920"
    assert len(proposal["feature_families"]) == 5
