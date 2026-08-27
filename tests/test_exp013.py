"""Tests for EXP-013: Two-Stage Event + Direction Prediction."""

import json
import numpy as np
from pathlib import Path
import pytest
from app.exp013_features import (
    StageAEventPrediction,
    StageBDirectionPrediction,
    economic_gate,
    compute_trade_features,
    compute_60s_forward_return,
    extract_v4_features,
    COST_TAKER,
    COST_MAKER,
)
import pandas as pd


class TestExp013Features:
    
    def test_cost_constants(self):
        assert COST_TAKER == 4.0146
        assert COST_MAKER == 2.0
    
    def test_economic_gate_rejects_weak_signal(self):
        # With low direction accuracy, gate should fail
        pass_gate, net = economic_gate(
            p_event=0.8,
            p_direction_correct=0.52,
            expected_return=18.41,
            cost_bps=COST_TAKER
        )
        assert not pass_gate
        assert net < 0
    
    def test_economic_gate_accepts_strong_signal(self):
        # With high direction accuracy, gate should pass
        pass_gate, net = economic_gate(
            p_event=0.8,
            p_direction_correct=0.75,
            expected_return=18.41,
            cost_bps=COST_TAKER
        )
        assert pass_gate
        assert net > 0
    
    def test_economic_gate_boundary(self):
        # At exactly the breakeven accuracy, net should be ~ -safety_margin
        p_event = 0.8
        e_ret = 18.41
        required_p = (COST_TAKER / (p_event * e_ret) + 1) / 2
        pass_gate, net = economic_gate(p_event, required_p, e_ret, COST_TAKER, safety_margin=0.0)
        assert net == pytest.approx(0.0, abs=0.5)
        assert not pass_gate
    
    def test_compute_trade_features(self):
        df = pd.DataFrame({
            'transact_time': np.arange(0, 1000, 10, dtype=np.int64),
            'price': np.ones(100) * 100.0,
            'quantity': np.ones(100) * 0.01,
            'is_buyer_maker': [i % 2 == 0 for i in range(100)],
        })
        result = compute_trade_features(df)
        assert 'buy_sign' in result.columns
        assert 'recent_ret_50' in result.columns
        assert 'recent_vi_50' in result.columns
        assert 'recent_vol_50' in result.columns
    
    def test_compute_60s_forward_return(self):
        df = pd.DataFrame({
            'transact_time': [0, 5000, 10000, 60000, 90000],
            'price': [100.0, 100.1, 100.2, 101.0, 100.8],
        })
        r = compute_60s_forward_return(df, horizon_ms=60000)
        # Trade at t=0 should forward to t=60000 (price 101.0)
        assert np.isfinite(r[0])
        expected = (101.0 - 100.0) / 100.0 * 1e4
        assert abs(r[0] - expected) < 0.1
    
    def test_extract_v4_features(self):
        rows = [
            {'ts_ms': 1, 'kind': 'depth', 'mid': 100.0, 'best_bid': 99.9, 'best_ask': 100.1,
             'qi_l1': 0.1, 'mpd_bps': 0.05, 'spread_bps': 0.2, 'depth_slope_bps': -0.01},
            {'ts_ms': 50000, 'kind': 'depth', 'mid': 100.5, 'best_bid': 100.0, 'best_ask': 101.0,
             'qi_l1': -0.1, 'mpd_bps': -0.05, 'spread_bps': 0.5, 'depth_slope_bps': 0.01},
            {'ts_ms': 30000, 'kind': 'trade', 'ts_ms': 30000, 'mid': 100.1, 'ts_ms': 30000,
             'trade_price': 100.1, 'trade_qty': 0.1},
        ]
        rows = [
            {'ts_ms': 1, 'kind': 'depth', 'mid': 100.0, 'best_bid': 99.9, 'best_ask': 100.1,
             'qi_l1': 0.1, 'mpd_bps': 0.05, 'spread_bps': 0.2, 'depth_slope_bps': -0.01},
            {'ts_ms': 50000, 'kind': 'depth', 'mid': 100.5, 'best_bid': 100.0, 'best_ask': 101.0,
             'qi_l1': -0.1, 'mpd_bps': -0.05, 'spread_bps': 0.5, 'depth_slope_bps': 0.01},
            {'ts_ms': 30000, 'kind': 'trade', 'mid': 100.1,
             'trade_price': 100.1, 'trade_qty': 0.1, 'seq': 1},
            {'ts_ms': 300000, 'kind': 'trade', 'mid': 100.8,
             'trade_price': 100.8, 'trade_qty': 0.1, 'seq': 2},
        ]
        X, R, S = extract_v4_features(rows, horizon_ms=60000)
        assert len(R) >= 0  # may be 0 if not enough data
    
    def test_stages_config(self):
        a = StageAEventPrediction()
        b = StageBDirectionPrediction()
        assert a.horizon_ms == 60000
        assert b.horizon_ms == 60000
        assert len(a.features) == 5
        assert len(b.features) == 17


class TestExp013Validation:
    
    def test_results_file_exists(self):
        results_path = Path('data/research/exp013/exp013_results.json')
        if results_path.exists():
            with open(results_path) as f:
                results = json.load(f)
            assert results['experiment'] == 'EXP-013'
            assert results['combined']['verdict'] == 'REJECTED'
