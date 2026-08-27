"""Tests for new V7 infrastructure components."""

import json
import pytest
import numpy as np
import pandas as pd
from pathlib import Path

from app.data_quality import verify_session, run_data_integrity_check
from app.experiment_registry import init_registry, add_experiment, list_experiments
from app.orchestrator import Orchestrator, Phase
from app.walk_forward import purged_split, walk_forward_splits, compute_label_windows
from app.v7_features import add_v7_features, V7_NEW_FEATURES
from app.v7_true_features import compute_multi_level_ofi, compute_queue_features


class TestDataQuality:
    """Tests for data integrity engine."""
    
    def test_verify_session_missing_dir(self, tmp_path):
        result = verify_session(tmp_path / "nonexistent")
        assert not result.passed
        assert "raw.jsonl not found" in result.errors[0]
    
    def test_verify_session_empty_dir(self, tmp_path):
        result = verify_session(tmp_path)
        assert not result.passed
        assert "raw.jsonl not found" in result.errors[0]
    
    def test_verify_session_valid_data(self, tmp_path):
        # Create minimal valid raw.jsonl
        raw = tmp_path / "raw.jsonl"
        snapshot = {
            "kind": "snapshot",
            "last_update_id": 1000,
            "ts_ms": 1000,
            "recv_ms": 1000,
            "bids": [[100.0, 1.0], [99.9, 2.0]],
            "asks": [[100.1, 1.0], [100.2, 2.0]],
        }
        depth = {
            "kind": "depth",
            "E": 1001,
            "U": 1001,
            "u": 1002,
            "recv_ms": 1001,
            "bids": [[100.0, 1.5]],
            "asks": [[100.1, 1.0]],
        }
        raw.write_text(json.dumps(snapshot) + "\n" + json.dumps(depth) + "\n")
        
        result = verify_session(tmp_path)
        assert result.passed
        assert result.snapshot_events == 1
        assert result.depth_events == 1
    
    def test_verify_session_crossed_book(self, tmp_path):
        raw = tmp_path / "raw.jsonl"
        snapshot = {
            "kind": "snapshot",
            "last_update_id": 1000,
            "ts_ms": 1000,
            "recv_ms": 1000,
            "bids": [[100.1, 1.0]],  # bid >= ask = crossed
            "asks": [[100.0, 1.0]],
        }
        raw.write_text(json.dumps(snapshot) + "\n")
        
        result = verify_session(tmp_path)
        assert not result.passed
        assert result.crossed_book_events == 1


class TestV7Features:
    """Tests for V7 feature engineering."""
    
    def test_add_v7_features_basic(self):
        """Test that V7 features are computed correctly."""
        df = pd.DataFrame({
            "ofi_l1": [1.0, 2.0, -1.0],
            "qi_l1": [0.1, -0.2, 0.3],
            "di_l5": [0.2, 0.3, -0.1],
            "di_l10": [0.15, 0.25, -0.05],
            "mpd_bps": [0.001, -0.002, 0.003],
            "tfi_500": [0.5, -0.3, 0.1],
            "signed_vol_500": [10.0, -5.0, 3.0],
            "mid": [100.0, 100.1, 100.2],
            "spread_bps": [0.1, 0.2, 0.15],
            "depth_slope_bps": [-0.01, -0.02, -0.015],
            "log_depth5": [5.0, 5.1, 4.9],
            "vol_500": [0.5, 0.6, 0.4],
            "vol_2000": [0.8, 0.9, 0.7],
            "regime": ["normal", "high_impact", "normal"],
            "log_depth1": [3.0, 3.1, 2.9],
            "log_event_rate": [2.0, 2.1, 1.9],
            "cancel_pressure": [0.1, 0.2, 0.05],
            "liq_depletion": [0.05, 0.1, 0.03],
            "bid_cancel_bps": [0.01, 0.02, 0.005],
            "ask_add_bps": [0.005, 0.01, 0.003],
            "ofi_norm_l1": [0.5, 1.0, -0.3],
        })
        
        result = add_v7_features(df)
        
        # Check new features exist
        for feat in V7_NEW_FEATURES:
            assert feat in result.columns, f"Missing feature: {feat}"
        
        # Check no NaN/inf
        for feat in V7_NEW_FEATURES:
            assert np.all(np.isfinite(result[feat])), f"Non-finite values in {feat}"
    
    def test_multi_level_ofi(self):
        """Test multi-level OFI computation from level snapshots."""
        prev_bids = [[100.0, 10.0], [99.9, 5.0]]
        prev_asks = [[100.1, 8.0], [100.2, 4.0]]
        
        # Current: bid at 100.0 increased, new bid at 99.8
        curr_bids = [[100.0, 15.0], [99.9, 5.0], [99.8, 3.0]]
        curr_asks = [[100.1, 6.0], [100.2, 4.0]]  # ask at 100.1 decreased
        
        result = compute_multi_level_ofi(prev_bids, prev_asks, curr_bids, curr_asks)
        
        # OFI net = (bid changes) - (ask changes)
        # Bid: (15-10) + (5-5) + (3-0) = 8
        # Ask: (6-8) + (4-4) = -2
        # Net = 8 - (-2) = 10
        assert result["ofi_net"] > 0  # Net positive (buy pressure)
        assert result["mlofi_weighted"] != 0
    
    def test_queue_features(self):
        """Test queue imbalance features."""
        bids = [[100.0, 20.0], [99.9, 10.0]]
        asks = [[100.1, 5.0], [100.2, 3.0]]
        
        result = compute_queue_features(bids, asks)
        
        # More bid qty than ask → positive imbalance
        assert result["qi_multi"] > 0
        assert result["depth_asymmetry"] > 0


class TestWalkForward:
    """Tests for walk-forward validation."""
    
    def test_purged_split(self):
        """Test purged chronological split."""
        ts = np.arange(1000, dtype=np.int64)
        labels_start = ts
        labels_end = ts + 100  # 100ms horizon
        
        train, val, oos = purged_split(ts, labels_start, labels_end,
                                        train_frac=0.7, val_frac=0.15)
        
        # Check disjoint sets
        assert not (train & val).any()
        assert not (train & oos).any()
        assert not (val & oos).any()
        
        # Check ordering: all train < all val < all oos
        train_ts = ts[train]
        val_ts = ts[val]
        oos_ts = ts[oos]
        
        if len(train_ts) > 0 and len(val_ts) > 0:
            assert train_ts.max() < val_ts.min()
        if len(val_ts) > 0 and len(oos_ts) > 0:
            assert val_ts.max() < oos_ts.min()
    
    def test_walk_forward_splits(self):
        """Test walk-forward window generation."""
        ts = np.arange(1000, dtype=np.int64)
        windows = walk_forward_splits(ts, n_windows=3)
        
        assert len(windows) == 3
        
        # Later windows should have more training data
        prev_train_size = 0
        for train_mask, test_mask in windows:
            assert train_mask.sum() > prev_train_size
            prev_train_size = train_mask.sum()
            
            # Train and test should be disjoint
            assert not (train_mask & test_mask).any()
    
    def test_compute_label_windows(self):
        """Test label window computation."""
        df = pd.DataFrame({"ts_ms": [1000, 2000, 3000]})
        start, end = compute_label_windows(df, horizon_ms=500)
        
        np.testing.assert_array_equal(start, [1000, 2000, 3000])
        np.testing.assert_array_equal(end, [1500, 2500, 3500])


class TestExperimentRegistry:
    """Tests for experiment registry."""
    
    def test_add_and_list(self, tmp_path, monkeypatch):
        """Test adding and listing experiments."""
        monkeypatch.chdir(tmp_path)
        
        registry_path = tmp_path / "research" / "experiment_registry.csv"
        monkeypatch.setattr("app.experiment_registry.REGISTRY_PATH", registry_path)
        
        init_registry()
        add_experiment(
            experiment_id="TEST-001",
            hypothesis="Test hypothesis",
            features="test_features",
            label_horizon_ms=500,
            model="Ridge",
            training_period="2026-01-01",
            validation_period="2026-01-02",
            test_period="2026-01-03",
            cost_model_bps=2.0,
            n_features=10,
            gross_expectancy_bps=0.05,
            net_expectancy_bps=-1.95,
            ci_low=-2.0,
            ci_high=-1.9,
            pct_above_gate=0.0,
            verdict="HYPOTHESIS_REJECTED",
        )
        
        experiments = list_experiments()
        assert len(experiments) == 1
        assert experiments[0]["experiment_id"] == "TEST-001"
        assert experiments[0]["verdict"] == "HYPOTHESIS_REJECTED"


class TestOrchestrator:
    """Tests for autonomous orchestrator."""
    
    def test_initial_status(self):
        orch = Orchestrator()
        status = orch.status()

        assert status["deployable_edge"] is False
        assert status["live_trading"] is False
        assert status["terminal_state"] is True  # Terminal: REJECTED after all experiments
        assert status["current_phase"] == Phase.REJECTED.value
    
    def test_terminal_state_rejected(self):
        orch = Orchestrator()
        orch.reject_hypothesis("Test rejection")
        
        assert orch.current_phase == Phase.REJECTED
        assert orch._is_terminal()
    
    def test_advance(self):
        orch = Orchestrator()
        initial_phase = orch.current_phase
        
        orch.advance(orch.current_phase, success=True)
        
        assert initial_phase in orch.completed_phases
        assert orch.current_phase != initial_phase or orch._is_terminal()
    
    def test_next_phase_determination(self):
        orch = Orchestrator()
        next_p = orch.next_phase()
        
        assert next_p is None  # Terminal: no next phase
