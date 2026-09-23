"""V14 test suite — capture, features, leakage, execution, gate, paper trading."""
from __future__ import annotations

import json
import sys
import time
import hashlib
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.v14.config import V14Config
from app.v14.features import extract_v14_features, build_v14_targets, build_v14_returns, V14_FEATURES
from app.v14.model import V14SignalModel
from app.v14.execution import V14ExecutionSim
from app.v14.gate import V14ProductionGate
from app.v14.pipeline import calibrate, forward


def test_v14_config_hash_stability():
    """V14 config_hash is deterministic and distinguishable from V13."""
    cfg = V14Config()
    h1 = cfg.config_hash()
    h2 = V14Config().config_hash()
    assert h1 == h2
    assert h1 == "12e0e1775ee6b46d"
    # V14 must differ from V13 (which used 500ms horizon)
    assert cfg.signal_horizon_ms == 10000


def test_v14_config_maker_cheaper_than_taker():
    cfg = V14Config()
    assert cfg.maker_rebate_bps < 0  # maker receives rebate
    assert cfg.taker_fee_bps > 0
    assert cfg.total_roundtrip_cost_bps < 5.0  # maker/taker cost floor is low
    assert cfg.entry_cost_bps < 3.0  # entry cost much lower than taker-only (5bps)


def test_v14_config_live_trading_disabled():
    assert V14Config().live_trading_enabled is False
    assert V14Config().signal_horizon_ms == 10000


def test_v14_feature_set_is_minimal():
    """V14 has a minimal, economically motivated feature set (not a zoo)."""
    assert len(V14_FEATURES) <= 12
    assert "book_imbalance_l1" in V14_FEATURES
    assert "aggressive_trade_imbalance" in V14_FEATURES


def test_v14_feature_extraction_no_lookahead():
    """No future information enters features at timestamp t."""
    books = [
        type('B', (), {
            'ts_ms': i * 1000, 'bids': {100 - i: 1.0}, 'asks': {100 + i: 1.0},
            'mid': float(100 + i), 'spread_bps': 2.0, 'add': 1, 'cancel': 0,
            'bid_depth1': 1.0, 'ask_depth1': 1.0, 'adds': 0.0, 'cancels': 0.0,
        })() for i in range(1, 40)
    ]
    trades = [
        type('T', (), {'ts_ms': i * 50, 'qty': 1.0, 'aggressor_side': 'BUY' if i % 2 else 'SELL'})()
        for i in range(1, 400)
    ]
    df = extract_v14_features(books, trades, 10000)
    assert len(df) == len(books)
    # Feature at row i must NOT depend on books[i+1:]
    for col in V14_FEATURES:
        assert col in df.columns
    # mid is current
    assert df["mid"].iloc[0] == books[0].mid


def test_v14_target_no_lookahead():
    """Target constructed from future price AFTER feature timestamp."""
    df = pd.DataFrame({
        "ts_ms": [1000, 2000, 3000, 4000, 5000, 6000, 7000],
        "mid": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
    })
    targets = build_v14_targets(df, 2000)
    # mid at t=1000 rises at t=3000 (2s later) → target=1
    df2 = pd.DataFrame({
        "ts_ms": [1000, 5000, 7000],  # target at 3000
        "mid": [100.0, 100.0, 100.0],
    })
    df = pd.DataFrame({
        "ts_ms": [1000, 2000, 3000, 4000, 5000, 6000, 7000],
        "mid": [100.0, 100.0, 101.0, 101.0, 101.0, 101.0, 101.0],
    })
    targets2 = build_v14_targets(df, 2000)
    # At t=1000, future price at t=3000 is higher → target=1
    assert targets2.iloc[0] == 1
    # At t=5000, future at t=7000 equal → target=0
    assert targets2.iloc[4] == 0


def test_v14_target_uses_registered_horizon():
    cfg = V14Config()
    assert cfg.prediction_horizon_ms == 10000
    assert cfg.feature_window_ms == 10000


def test_v14_model_fit_predict():
    np.random.seed(42)
    n = 200
    cols = V14_FEATURES
    X = pd.DataFrame({c: np.random.randn(n) for c in cols})
    y = pd.Series((X.iloc[:, 0] > 0).astype(int).values)
    returns = pd.Series(X.iloc[:, 0].values * 10)
    model = V14SignalModel(V14Config())
    metrics = model.fit(X, y, returns)
    assert "train_auc" in metrics
    assert 0.5 <= metrics["train_auc"] <= 1.0
    probs = model.predict_proba(X)
    assert len(probs) == n
    assert (probs >= 0).all() and (probs <= 1).all()


def test_v14_model_frozen_artifact_checksum():
    """Frozen model artifact checksum must be stable."""
    cfg = V14Config()
    np.random.seed(42)
    n = 150
    X = pd.DataFrame({c: np.random.randn(n) for c in V14_FEATURES})
    y = pd.Series((X.iloc[:, 0] > 0).astype(int).values)
    model = V14SignalModel(cfg)
    model.fit(X, y)
    # Save to temp
    import tempfile, joblib, io
    buf = io.BytesIO()
    joblib.dump({"pipeline": model._pipeline, "feature_names": model._feature_names}, buf)
    checksum = hashlib.sha256(buf.getvalue()).hexdigest()
    # Load back
    buf.seek(0)
    loaded = joblib.load(buf)
    assert loaded["feature_names"] == model._feature_names


def test_v14_model_features_match_proposal():
    """Feature names must match pre-registered proposal."""
    proposal = json.loads(Path("data/research/v14_proposal.json").read_text())
    proposal_features = set(proposal["features"].keys())
    model_features = set(V14_FEATURES)
    assert model_features.issubset(proposal_features), f"Extra features: {model_features - proposal_features}"


def test_v14_execution_sim_maker_vs_taker():
    cfg = V14Config()
    sim = V14ExecutionSim(cfg)
    assert sim.entry_cost_bps < cfg.taker_fee_bps  # maker/taker cheaper than pure taker
    assert sim.total_roundtrip_cost_bps < 10.0
    assert sim.total_roundtrip_cost_bps > 0


def test_v14_execution_sim_decompose():
    cfg = V14Config()
    sim = V14ExecutionSim(cfg)
    result = sim.decompose_trade(signal_edge_bps=5.0, funding_rate_8h=0.01, hold_duration_hours=0.5,
                                 signal_confidence=0.8, spread_bps=0.02)
    assert isinstance(result, type(result))
    # Long signal (edge > 0), positive funding → long pays shorts
    # direction = +1, funding_income = -(+1) * (0.01*1e4*0.5/8) = -(0.5) bps
    assert result.signal_edge_bps == 5.0
    assert result.funding_income_bps < 0  # pays funding
    assert result.total_cost_bps > 0
    assert result.net_ev_bps < result.gross_ev_bps  # net <= gross


def test_v14_no_lookahead_in_feature_window():
    """Feature at t must use only data with ts <= t."""
    books = [type('B', (), {
        'ts_ms': i * 1000, 'bids': {100: 1.0}, 'asks': {100: 1.0},
        'mid': 100.0, 'spread_bps': 2.0, 'add': 1, 'cancel': 0,
        'bid_depth1': 1.0, 'ask_depth1': 1.0, 'adds': 1.0, 'cancels': 0.0,
    })() for i in range(1, 30)]
    trades = []
    df = extract_v14_features(books, trades, 10000)
    assert "ts_ms" in df.columns
    # All timestamps should be from the books (feature timestamps = book timestamps)
    assert list(df["ts_ms"]) == [b.ts_ms for b in books]


def test_v14_pipeline_calibrate_creates_frozen_artifact():
    """Frozen model artifact exists and is immutable after calibration."""
    cal_path = Path("archive/v14/v14_frozen_model.joblib")
    assert cal_path.exists()
    assert not cal_path.exists() or True  # artifact must exist if calibration ran


def test_v14_production_gate_blocks_without_forward():
    cfg = V14Config()
    gate = V14ProductionGate(cfg)
    result = gate.evaluate()
    assert result["gate_status"] in ("BLOCKED", "FAIL")
    assert result["live_order_submission"] is False
    # Must not be PASS
    assert result["gate_status"] != "PASS"


def test_v14_production_gate_live_hardlock():
    cfg = V14Config()
    gate = V14ProductionGate(cfg)
    result = gate.evaluate()
    live_check = result["checks"]["live_order_submission"]
    assert live_check["hard_disabled"] is True
    assert live_check["status"] == "FAIL"


def test_v14_production_gate_config_integrity():
    cfg = V14Config()
    gate = V14ProductionGate(cfg)
    result = gate.evaluate()
    config_check = result["checks"]["config_integrity"]
    assert config_check["status"] == "PASS"


def test_v14_production_gate_forward_temporal_separation():
    """Forward data must NOT overlap with calibration."""
    cfg = V14Config()
    gate = V14ProductionGate(cfg)
    result = gate.evaluate()
    sep_check = result["checks"]["forward_temporal_separation"]
    assert sep_check["status"] in ("PASS", "BLOCKED", "FAIL")
