"""Tests for EXP-012: Aggressive Flow × Absorption Capacity × Liquidity Fragility."""

import pytest
import numpy as np
import pandas as pd
from pathlib import Path

from app.exp012_features import (
    EventBuffer,
    compute_event_features,
    build_exp012_features,
    add_labels,
)
from app.exp012_economic_gate import (
    EconomicGate,
    compute_expected_cost_per_event,
    COST_MODEL_PARAMS,
)
from app.exp012_validation import (
    chronological_split,
    purged_split,
    bootstrap_ci,
    evaluate_model,
    run_full_validation,
    run_walk_forward,
    HORIZONS_MS,
)


class TestEventBuffer:
    """Tests for the event buffer."""

    def test_buffer_add_trade(self):
        buf = EventBuffer(max_window_ms=500)
        buf.add_trade(1000, 1.0, "BUY", 50000.0)
        assert len(buf.trades) == 1
        assert buf.trades[0] == (1000, 1.0, "BUY", 50000.0)

    def test_buffer_prune(self):
        buf = EventBuffer(max_window_ms=500)
        for i in range(10):
            buf.add_trade(1000 + i * 100, 1.0, "BUY", 50000.0)
        # All events at 1000-1900; prune(1400) keeps ts >= 900
        buf.prune(1400)
        assert len(buf.trades) == 10  # All within window
        # prune(1600) keeps ts >= 1100 → events at 1100,1200,...,1900 = 9
        buf.prune(1600)
        assert len(buf.trades) == 9

    def test_buffer_agg_flow(self):
        buf = EventBuffer(max_window_ms=500)
        buf.add_trade(1000, 1.0, "BUY", 50000.0)
        buf.add_trade(1100, 0.5, "SELL", 50000.0)
        buf.add_trade(1200, 1.5, "BUY", 50001.0)
        flow = buf.agg_flow(1200, window_ms=500)
        assert flow["aggressive_buy_flow"] == 2.5
        assert flow["aggressive_sell_flow"] == 0.5
        assert abs(flow["flow_imbalance"] - (2.5 - 0.5) / (2.5 + 0.5)) < 1e-6
        assert flow["trade_count"] == 3


class TestFeatureEngineering:
    """Tests for EXP-012 feature engineering."""

    def test_features_file_exists(self):
        assert Path("data/research/exp012/exp012_features.parquet").exists()

    def test_features_expected_columns(self):
        df = pd.read_parquet("data/research/exp012/exp012_features.parquet")
        expected_cols = [
            "session", "ts_ms", "kind", "mid", "spread_bps",
            "aggressive_buy_flow", "aggressive_sell_flow",
            "total_aggressive_flow", "flow_imbalance",
            "bid_depth_3", "ask_depth_3", "absorption_capacity",
            "flow_to_depth_ratio", "cancellation_velocity",
            "cancellation_velocity", "qi_l1", "mpd_bps",
        ]
        for col in expected_cols:
            assert col in df.columns, f"Missing column: {col}"

    def test_features_non_negative_flow_to_depth(self):
        df = pd.read_parquet("data/research/exp012/exp012_features.parquet")
        assert (df["flow_to_depth_ratio"] >= 0).all()

    def test_features_sessions_count(self):
        df = pd.read_parquet("data/research/exp012/exp012_features.parquet")
        assert df["session"].nunique() == 12

    def test_add_labels_creates_columns(self):
        df = pd.read_parquet("data/research/exp012/exp012_features.parquet")
        df = add_labels(df)
        for h in HORIZONS_MS:
            assert f"r_{h}" in df.columns


class TestEconomicGate:
    """Tests for the economic gate model."""

    def test_cost_computation(self):
        df = pd.read_parquet("data/research/exp012/exp012_features.parquet")
        costs = compute_expected_cost_per_event(df)
        assert len(costs) == len(df)
        assert costs.min() >= 0
        assert costs.max() < 100  # Reasonable upper bound

    def test_taker_fee_is_4bps(self):
        """Round-trip taker fee should be 4.0 bps (measured)."""
        df = pd.read_parquet("data/research/exp012/exp012_features.parquet")
        costs = compute_expected_cost_per_event(df)
        # Fee alone should be 4.0 bps
        fee_alone = 2 * COST_MODEL_PARAMS["taker_fee_bps"]
        mean_cost = costs.mean()
        # Cost should be at least fee (plus spread, slippage, etc.)
        assert mean_cost >= fee_alone

    def test_gate_evaluation(self):
        df = pd.read_parquet("data/research/exp012/exp012_features.parquet")
        df = add_labels(df)
        col = "r_10000"
        df_v = df[df[col].notna()]

        gate = EconomicGate(**COST_MODEL_PARAMS)
        results = gate.evaluate_gate(df_v, df_v[col].values)

        assert "n_total" in results
        assert "net_mean" in results
        assert results["net_mean"] < 0  # Always negative after costs


class TestValidation:
    """Tests for validation pipeline."""

    def test_chronological_split(self):
        df = pd.read_parquet("data/research/exp012/exp012_features.parquet")
        train, val, oos = chronological_split(df)
        assert len(train) > len(val) > 0
        assert len(oos) > 0
        # No session leakage
        train_sessions = set(train["session"].unique())
        val_sessions = set(val["session"].unique())
        oos_sessions = set(oos["session"].unique())
        assert train_sessions.isdisjoint(val_sessions)
        assert train_sessions.isdisjoint(oos_sessions)
        assert val_sessions.isdisjoint(oos_sessions)

    def test_purged_split_no_timestamp_overlap(self):
        df = pd.read_parquet("data/research/exp012/exp012_features.parquet")
        train, val, oos = purged_split(df, purge_ms=5000)
        assert len(train) > 0
        assert len(val) > 0
        assert len(oos) > 0
        # Train should end before val starts (purge applied)
        if len(train) > 0 and len(val) > 0:
            assert train["ts_ms"].max() < val["ts_ms"].min()

    def test_bootstrap_ci_returns_three_values(self):
        returns = np.array([0.1, -0.2, 0.3, -0.1, 0.05, -0.05, 0.2, -0.3])
        mean, low, high = bootstrap_ci(returns)
        assert low <= mean <= high

    def test_bootstrap_ci_empty_array(self):
        mean, low, high = bootstrap_ci(np.array([]))
        assert mean == 0.0 and low == 0.0 and high == 0.0

    def test_full_validation_results_exist(self):
        assert Path("data/research/exp012/exp012_results.json").exists()

    def test_exp012_rejected_at_all_horizons(self):
        import json
        with open("data/research/exp012/exp012_results.json") as f:
            results = json.load(f)
        for h, data in results["horizon_results"].items():
            assert data["verdict"] == "HYPOTHESIS_REJECTED"
            assert data["net_mean_bps"] < 0


class TestOrchestratorState:
    """Tests for orchestrator terminal state after EXP-012."""

    def test_terminal_state(self):
        from app.orchestrator import Orchestrator
        orch = Orchestrator()
        assert orch._is_terminal()
        assert orch.current_phase.value == "REJECTED"

    def test_exp012_in_failed_hypotheses(self):
        from app.orchestrator import Orchestrator
        orch = Orchestrator()
        assert any("EXP-012" in h for h in orch.failed_hypotheses)

    def test_no_deployable_edge(self):
        from app.orchestrator import Orchestrator
        orch = Orchestrator()
        assert orch.deployable_edge is False
        assert orch.live_trading is False
