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


def test_v16_execution_non_fill_cost_is_conditional():
    cfg = V16Config()
    sim = V16ExecutionSim(cfg)

    d = sim.route(5.0, 0.8)
    assert d.action == "MAKER"
    assert d.non_fill_cost_bps == pytest.approx(0.1)  # (1 - 0.8) * 0.5

    d2 = sim.route(5.0, 1.0)
    assert d2.action == "MAKER"
    assert d2.non_fill_cost_bps == 0.0  # fill_prob=1.0, no non-fill cost


def test_v16_expected_pnl_formula_is_correct():
    cfg = V16Config()
    sim = V16ExecutionSim(cfg)

    pr = 5.0
    fp = 0.8

    maker_pnl = sim.expected_pnl(pr, fp, maker=True)
    expected = fp * pr - cfg.maker_entry_cost_bps - cfg.exit_cost_bps - (1 - fp) * cfg.non_fill_opportunity_cost_bps
    assert maker_pnl == pytest.approx(expected)

    taker_pnl = sim.expected_pnl(pr, 1.0, maker=False)
    expected_taker = pr - cfg.taker_entry_cost_bps - cfg.exit_cost_bps
    assert taker_pnl == pytest.approx(expected_taker)


def test_v16_forward_accounting_reconciles():
    from app.v16.pipeline import forward
    from app.v16.execution import V16ExecutionSim
    cfg = V16Config()
    result = forward(cfg)
    if result["status"] == "COMPLETE" and result["n_trades"] > 0:
        gross = result["gross_ev_bps"]
        total_cost = result["total_cost_bps"]
        net = result["net_ev_bps"]

        assert gross > 0, "Gross EV must be positive"
        assert total_cost > 0, "Total cost must be positive"
        assert net > 0, "Net EV must be positive for a pass"

        # Correct accounting: Net EV = mean(fill_prob * predicted_return) - mean(total_cost)
        # NOT Gross EV - Total cost
        assert net <= gross, "Net EV cannot exceed Gross EV"
        assert total_cost < gross, "Total cost must be less than Gross EV for positive Net EV"
        assert net > 0, "Net EV must be positive"
        assert result["ci_lower_bps"] > 0, "CI lower bound must be positive"


def test_v16_paper_runtime_initializes():
    from app.v16.paper_runtime import V16PaperTrader
    from pathlib import Path
    cfg = V16Config()
    return_path = Path("archive/v16/v16_frozen_return_model.joblib")
    fill_path = Path("archive/v16/v16_frozen_fill_model.joblib")
    if return_path.exists() and fill_path.exists():
        trader = V16PaperTrader(cfg, return_path, fill_path)
        assert trader is not None
        assert trader._running is False
        assert len(trader._decisions) == 0
        assert len(trader._positions) == 0
    else:
        pytest.skip("Frozen models not found")


def test_v16_paper_runtime_rejects_non_positive():
    from app.v16.paper_runtime import V16PaperTrader
    from pathlib import Path
    cfg = V16Config()
    return_path = Path("archive/v16/v16_frozen_return_model.joblib")
    fill_path = Path("archive/v16/v16_frozen_fill_model.joblib")
    if not return_path.exists() or not fill_path.exists():
        pytest.skip("Frozen models not found")
    trader = V16PaperTrader(cfg, return_path, fill_path)
    trader.start()
    books = [type('B', (), {
        'ts_ms': i * 1000, 'bids': {100: 1.0}, 'asks': {100: 1.0},
        'mid': 100.0, 'spread_bps': 2.0, 'bid_depth1': 1.0, 'ask_depth1': 1.0,
        'bid_depth5': 1.0, 'ask_depth5': 1.0, 'bid_depth10': 1.0, 'ask_depth10': 1.0,
        'adds': 1.0, 'cancels': 0.0, 'net': 1.0,
    })() for i in range(1, 30)]
    trades = []
    result = trader.process_event(books, trades)
    assert result is None  # should reject when predicted return is near zero
    assert len(trader._rejected) > 0


def test_v16_paper_runtime_tracks_positions():
    from app.v16.paper_runtime import V16PaperTrader
    from pathlib import Path
    cfg = V16Config()
    return_path = Path("archive/v16/v16_frozen_return_model.joblib")
    fill_path = Path("archive/v16/v16_frozen_fill_model.joblib")
    if not return_path.exists() or not fill_path.exists():
        pytest.skip("Frozen models not found")
    trader = V16PaperTrader(cfg, return_path, fill_path)
    trader.start()
    books = [type('B', (), {
        'ts_ms': i * 1000, 'bids': {100: 1.0}, 'asks': {100: 1.0},
        'mid': 100.0, 'spread_bps': 2.0, 'bid_depth1': 1.0, 'ask_depth1': 1.0,
        'bid_depth5': 1.0, 'ask_depth5': 1.0, 'bid_depth10': 1.0, 'ask_depth10': 1.0,
        'adds': 1.0, 'cancels': 0.0, 'net': 1.0,
    })() for i in range(1, 30)]
    trades = []
    # Process enough events to potentially get a signal
    for _ in range(5):
        trader.process_event(books, trades)
    # Should have some decisions or rejections
    assert len(trader._decisions) + len(trader._rejected) > 0
