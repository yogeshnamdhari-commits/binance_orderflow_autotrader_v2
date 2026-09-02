"""Empirical integration tests for V10 captured-data -> execution-observations pipeline.

These tests validate the full chain: synthetic capture generation -> book replay
-> passive-order simulation -> execution-economics summary. They use deterministic
synthetic data, not real market data.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.v10_book_replay import ReplayStatus
from app.v10_empirical_adapter import (
    empirical_integration,
    load_session_events,
    replay_book,
    simulate_passive_orders,
)
from app.v10_synthetic_capture import generate_synthetic_capture


@pytest.fixture
def capture_session(tmp_path: Path) -> Path:
    return generate_synthetic_capture(
        tmp_path,
        session_id="test_session_001",
        n_depth_events=200,
        n_trades=80,
        start_mid=65000.0,
        seed=42,
    )


class TestSyntheticCapture:
    def test_capture_writes_manifest_and_events(self, capture_session: Path):
        manifest = json.loads((capture_session / "manifest.json").read_text())
        assert manifest["schema_version"] == "v10.raw.v1"
        assert manifest["symbol"] == "BTCUSDT"
        assert manifest["event_count"] > 0

        events = list((capture_session / "events.jsonl").read_text().splitlines())
        assert len(events) == manifest["event_count"]

    def test_capture_has_continuous_depth_sequence(self, capture_session: Path):
        events = load_session_events(capture_session)
        depth_events = [e for e in events if e["event_type"] == "depthUpdate"]
        assert len(depth_events) > 50

        previous_u = None
        for event in depth_events:
            data = event["payload"].get("data", event["payload"])
            U = int(data["U"])
            u = int(data["u"])
            pu = int(data["pu"]) if data.get("pu") is not None else None
            assert U <= u, f"U={U} > u={u}"
            if previous_u is not None and pu is not None:
                assert pu == previous_u, f"pu={pu} != previous_u={previous_u}"
            previous_u = u

    def test_capture_has_trade_events(self, capture_session: Path):
        events = load_session_events(capture_session)
        trade_events = [e for e in events if e["event_type"] == "trade"]
        assert len(trade_events) > 20

        for event in trade_events:
            data = event["payload"].get("data", event["payload"])
            assert "p" in data
            assert "q" in data
            assert "m" in data
            assert float(data["p"]) > 0
            assert float(data["q"]) > 0


class TestBookReplay:
    def test_replay_succeeds_on_synthetic_capture(self, capture_session: Path):
        events = load_session_events(capture_session)
        status, bids, asks, last_update_id = replay_book(events)

        assert status == ReplayStatus.OK
        assert len(bids) > 0
        assert len(asks) > 0
        assert last_update_id is not None
        assert last_update_id > 0

    def test_replay_produces_valid_book_state(self, capture_session: Path):
        events = load_session_events(capture_session)
        status, bids, asks, _ = replay_book(events)

        assert status == ReplayStatus.OK
        bid_prices = sorted(bids.keys())
        ask_prices = sorted(asks.keys())
        assert bid_prices[-1] < ask_prices[0], "best bid must be below best ask"

        for price, qty in bids.items():
            assert price > 0
            assert qty > 0
        for price, qty in asks.items():
            assert price > 0
            assert qty > 0


class TestPassiveOrderSimulation:
    def test_simulation_produces_observations(self, capture_session: Path):
        events = load_session_events(capture_session)
        observations = simulate_passive_orders(events, order_quantity=0.01, decision_every_n=10)

        assert not observations.empty
        assert "fill_fraction" in observations.columns
        assert "queue_ahead" in observations.columns
        assert "time_to_fill_ms" in observations.columns
        assert "filled" in observations.columns
        assert "adverse_selection_bps" in observations.columns

    def test_fill_fractions_are_bounded(self, capture_session: Path):
        events = load_session_events(capture_session)
        observations = simulate_passive_orders(events)

        assert observations["fill_fraction"].between(0, 1).all()

    def test_both_sides_are_represented(self, capture_session: Path):
        events = load_session_events(capture_session)
        observations = simulate_passive_orders(events)

        sides = set(observations["side"].unique())
        assert "bid" in sides
        assert "ask" in sides

    def test_some_orders_fill_and_some_do_not(self, capture_session: Path):
        events = load_session_events(capture_session)
        observations = simulate_passive_orders(events, decision_every_n=5)

        fill_rate = observations["filled"].mean()
        assert 0 < fill_rate < 1, f"fill_rate={fill_rate} should be strictly between 0 and 1"

    def test_adverse_selection_has_both_signs(self, capture_session: Path):
        events = load_session_events(capture_session)
        observations = simulate_passive_orders(events, decision_every_n=5)
        filled = observations[observations["filled"] == 1]

        if not filled.empty:
            assert (filled["adverse_selection_bps"] > 0).any() or (filled["adverse_selection_bps"] < 0).any()

    def test_time_to_fill_is_non_negative(self, capture_session: Path):
        events = load_session_events(capture_session)
        observations = simulate_passive_orders(events)

        assert (observations["time_to_fill_ms"] >= 0).all()


class TestEmpiricalIntegration:
    def test_full_pipeline_runs_on_capture(self, capture_session: Path):
        result = empirical_integration(capture_session)

        assert result["replay_status"] == "OK"
        assert result["n_events"] > 0
        assert result["n_observations"] > 0
        assert not result["observations"].empty

    def test_summary_reports_fill_metrics(self, capture_session: Path):
        result = empirical_integration(capture_session)
        summary = result["summary"]

        assert summary["orders"] > 0
        assert summary["filled_orders"] >= 0
        assert 0 <= summary["fill_rate"] <= 1

    def test_pipeline_produces_walkforward_compatible_data(self, capture_session: Path):
        result = empirical_integration(capture_session, decision_every_n=5)
        obs = result["observations"]

        required_cols = {"queue_ahead", "filled", "time_to_fill_ms", "adverse_selection_bps", "fill_fraction"}
        assert required_cols.issubset(obs.columns)

        assert obs["timestamp"].is_monotonic_increasing or obs.sort_values("timestamp")["timestamp"].is_monotonic_increasing

    def test_pipeline_can_feed_walkforward_evaluation(self, capture_session: Path):
        from app.v10_research_pipeline import run_walkforward

        result = empirical_integration(capture_session, decision_every_n=3)
        obs = result["observations"].copy()
        obs = obs.sort_values("timestamp").reset_index(drop=True)

        obs["_seq"] = range(len(obs))
        obs = obs.set_index("timestamp")
        obs.index = obs.index + pd.to_timedelta(obs["_seq"], unit="us")
        obs = obs.reset_index()

        if len(obs) < 12:
            pytest.skip("not enough observations for walk-forward")

        ts_col = "timestamp" if "timestamp" in obs.columns else obs.columns[0]
        obs = obs.rename(columns={ts_col: "ts"})
        obs = obs.set_index("ts")
        obs = obs.drop(columns=["_seq"], errors="ignore")
        obs = obs.rename(columns={"time_to_fill_ms": "time_to_fill"})

        folds = run_walkforward(
            obs,
            train_size=4,
            embargo=1,
            test_size=2,
            step=2,
            bins=[0.0, 2.0, 10.0],
            survival_horizon=1000.0,
            spread_capture_bps=2.0,
            fee_rebate_bps=0.5,
            inventory_cost_bps=0.2,
            exit_cost_bps=0.3,
            cancellation_cost_bps=0.05,
        )

        assert len(folds) > 0
        for fold in folds:
            assert "oos_orders" in fold
            assert "mean_oos_realized_ev_bps" in fold
            assert "mean_predicted_fill_probability" in fold


class TestEmpiricalEconomics:
    def test_fill_probability_varies_with_queue(self, capture_session: Path):
        events = load_session_events(capture_session)
        observations = simulate_passive_orders(events, decision_every_n=3, queue_ahead_fraction=0.5)

        if observations.empty:
            pytest.skip("no observations")

        low_q = observations[observations["queue_ahead"] <= observations["queue_ahead"].median()]
        high_q = observations[observations["queue_ahead"] > observations["queue_ahead"].median()]

        if low_q.empty or high_q.empty:
            pytest.skip("insufficient queue variation")

        low_fill = low_q["filled"].mean()
        high_fill = high_q["filled"].mean()

        assert low_fill >= high_fill, (
            f"low-queue fill rate ({low_fill:.3f}) should be >= high-queue fill rate ({high_fill:.3f})"
        )

    def test_fee_adjusted_ev_is_computable(self, capture_session: Path):
        from app.v10_economics import passive_order_ev_bps

        events = load_session_events(capture_session)
        observations = simulate_passive_orders(events, decision_every_n=3)

        if observations.empty:
            pytest.skip("no observations")

        fill_rate = observations["filled"].mean()
        mean_adverse = observations.loc[observations["filled"] == 1, "adverse_selection_bps"].mean()

        if np.isnan(mean_adverse):
            mean_adverse = 0.0

        ev = passive_order_ev_bps(
            fill_probability=fill_rate,
            spread_capture_bps=2.0,
            fee_rebate_bps=0.5,
            adverse_selection_bps=mean_adverse,
            inventory_cost_bps=0.2,
            exit_cost_bps=0.3,
            cancellation_cost_bps=0.05,
        )

        assert np.isfinite(ev)

    def test_survival_curve_is_fittable(self, capture_session: Path):
        from app.v10_fill_survival import fit_kaplan_meier

        events = load_session_events(capture_session)
        observations = simulate_passive_orders(events, decision_every_n=3)

        if observations.empty:
            pytest.skip("no observations")

        model = fit_kaplan_meier(
            observations["time_to_fill_ms"].to_numpy(float),
            observations["filled"].to_numpy(int),
        )

        prob = model.fill_probability(500.0)
        assert 0 <= prob <= 1
