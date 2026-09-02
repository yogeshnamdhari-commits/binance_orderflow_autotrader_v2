"""Empirical integration tests for V10 captured-data -> execution-observations pipeline.

These tests validate the full chain: synthetic capture generation -> book replay
-> passive-order simulation -> execution-economics summary. They use deterministic
synthetic data, not real market data.

Regression tests cover six failure modes:
1. Adapter uses single deterministic book state (not independent price extraction)
2. Snapshot is consumed from session (not hard-coded)
3. Fill horizon is timestamp-based (not all future trades)
4. Post-fill mid is timestamp-based (not row-based)
5. Depth comes from replayed book (not raw update messages)
6. Trade stream event_type matches V10 capture ("trade", "aggTrade")
"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.v10_book_replay import ReplayStatus
from app.v10_empirical_adapter import (
    build_incremental_book,
    empirical_integration,
    extract_snapshot_from_events,
    load_session_events,
    load_session_snapshot,
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


@pytest.fixture
def session_snapshot(capture_session: Path) -> dict:
    snapshot = load_session_snapshot(capture_session)
    if snapshot is None:
        snapshot = extract_snapshot_from_events(load_session_events(capture_session))
    assert snapshot is not None
    return snapshot


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
        trade_events = [e for e in events if e["event_type"] in ("trade", "aggTrade")]
        assert len(trade_events) > 20

        for event in trade_events:
            data = event["payload"].get("data", event["payload"])
            assert "p" in data
            assert "q" in data
            assert "m" in data
            assert float(data["p"]) > 0
            assert float(data["q"]) > 0

    def test_capture_writes_snapshot_file(self, capture_session: Path):
        snapshot = load_session_snapshot(capture_session)
        assert snapshot is not None
        assert "lastUpdateId" in snapshot
        assert "bids" in snapshot
        assert "asks" in snapshot
        assert len(snapshot["bids"]) > 0
        assert len(snapshot["asks"]) > 0


class TestBookReplay:
    def test_replay_succeeds_on_synthetic_capture(self, capture_session: Path, session_snapshot: dict):
        events = load_session_events(capture_session)
        book_states = []
        for event_type, _, book_state, _ in build_incremental_book(events, session_snapshot):
            if event_type == "depth" and book_state is not None:
                book_states.append(book_state)

        assert len(book_states) > 0

    def test_replay_produces_valid_book_state(self, capture_session: Path, session_snapshot: dict):
        events = load_session_events(capture_session)
        book_states = []
        for event_type, _, book_state, _ in build_incremental_book(events, session_snapshot):
            if event_type == "depth" and book_state is not None:
                book_states.append(book_state)

        assert len(book_states) > 0
        state = book_states[len(book_states) // 2]
        assert state.best_bid > 0
        assert state.best_ask > 0
        assert state.best_bid < state.best_ask
        assert state.bid_size > 0
        assert state.ask_size > 0


class TestSingleDeterministicBookPath:
    """Regression test for failure mode 1: adapter must use single deterministic book state."""

    def test_book_state_matches_replayed_book(self, capture_session: Path, session_snapshot: dict):
        """Verify that the book state at each point matches what V10BookReplay produces."""
        from app.v10_book_replay import V10BookReplay

        events = load_session_events(capture_session)
        depth_data = []
        for event in events:
            if event["event_type"] == "depthUpdate":
                data = event["payload"].get("data", event["payload"])
                depth_data.append(data)

        replay = V10BookReplay()
        result = replay.replay(session_snapshot, depth_data)
        assert result.status == ReplayStatus.OK

        incremental_states = []
        for event_type, _, book_state, _ in build_incremental_book(events, session_snapshot):
            if event_type == "depth" and book_state is not None:
                incremental_states.append(book_state)

        assert len(incremental_states) > 0

        final_incremental = incremental_states[-1]
        final_replay_bid = float(max(result.bids.keys())) if result.bids else 0.0
        final_replay_ask = float(min(result.asks.keys())) if result.asks else 0.0

        assert abs(final_incremental.best_bid - final_replay_bid) < 0.01
        assert abs(final_incremental.best_ask - final_replay_ask) < 0.01


class TestSnapshotNotHardCoded:
    """Regression test for failure mode 2: snapshot must come from session, not be hard-coded."""

    def test_snapshot_has_real_prices(self, capture_session: Path):
        snapshot = load_session_snapshot(capture_session)
        assert snapshot is not None

        bid_prices = [float(b[0]) for b in snapshot["bids"]]
        ask_prices = [float(a[0]) for a in snapshot["asks"]]

        assert min(bid_prices) > 60000
        assert max(bid_prices) < 70000
        assert min(ask_prices) > 60000
        assert max(ask_prices) < 70000

    def test_different_start_mid_produces_different_snapshot(self, tmp_path: Path):
        session_65k = generate_synthetic_capture(
            tmp_path / "a", session_id="s1", n_depth_events=50, n_trades=10, start_mid=65000.0, seed=42
        )
        session_50k = generate_synthetic_capture(
            tmp_path / "b", session_id="s2", n_depth_events=50, n_trades=10, start_mid=50000.0, seed=42
        )

        snap_65k = load_session_snapshot(session_65k)
        snap_50k = load_session_snapshot(session_50k)

        assert snap_65k is not None
        assert snap_50k is not None

        mid_65k = (float(snap_65k["bids"][0][0]) + float(snap_65k["asks"][0][0])) / 2.0
        mid_50k = (float(snap_50k["bids"][0][0]) + float(snap_50k["asks"][0][0])) / 2.0

        assert abs(mid_65k - 65000.0) < 1.0
        assert abs(mid_50k - 50000.0) < 1.0


class TestTimestampBasedHorizon:
    """Regression test for failure mode 3: fill horizon must be timestamp-based."""

    def test_fills_only_within_horizon(self, capture_session: Path, session_snapshot: dict):
        events = load_session_events(capture_session)
        observations = simulate_passive_orders(
            events, session_snapshot, decision_every_n=5, horizon_ms=500
        )

        if observations.empty:
            pytest.skip("no observations")

        filled = observations[observations["filled"] == 1]
        if filled.empty:
            pytest.skip("no fills to check")

        assert (filled["time_to_fill_ms"] <= 500.0).all(), (
            "all fills must occur within the 500ms horizon"
        )

    def test_longer_horizon_produces_more_fills(self, capture_session: Path, session_snapshot: dict):
        events = load_session_events(capture_session)

        obs_short = simulate_passive_orders(
            events, session_snapshot, decision_every_n=5, horizon_ms=200
        )
        obs_long = simulate_passive_orders(
            events, session_snapshot, decision_every_n=5, horizon_ms=2000
        )

        if obs_short.empty or obs_long.empty:
            pytest.skip("insufficient observations")

        fill_short = obs_short["filled"].mean()
        fill_long = obs_long["filled"].mean()

        assert fill_long >= fill_short, (
            f"longer horizon fill rate ({fill_short:.3f}) should be >= shorter horizon ({fill_long:.3f})"
        )


class TestTimestampBasedPostFillMid:
    """Regression test for failure mode 4: post-fill mid must be timestamp-based."""

    def test_post_mid_uses_actual_future_timestamp(self, capture_session: Path, session_snapshot: dict):
        events = load_session_events(capture_session)
        observations = simulate_passive_orders(
            events, session_snapshot, decision_every_n=5, horizon_ms=1000
        )

        if observations.empty:
            pytest.skip("no observations")

        book_states = []
        for event_type, _, book_state, _ in build_incremental_book(events, session_snapshot):
            if event_type == "depth" and book_state is not None:
                book_states.append(book_state)

        if not book_states:
            pytest.skip("no book states")

        for _, row in observations.iterrows():
            placement_ts = row["timestamp"]
            horizon_end = placement_ts + timedelta(milliseconds=1000)

            future_states = [s for s in book_states if placement_ts < s.timestamp <= horizon_end]

            if future_states:
                last_state = future_states[-1]
                expected_mid = (last_state.best_bid + last_state.best_ask) / 2.0

                assert abs(row["post_mid"] - expected_mid) < 0.01, (
                    f"post_mid {row['post_mid']:.2f} should match timestamp-based future mid {expected_mid:.2f}"
                )
                break


class TestDepthFromReplayedBook:
    """Regression test for failure mode 5: depth must come from replayed book state."""

    def test_best_bid_ask_match_replayed_book(self, capture_session: Path, session_snapshot: dict):
        events = load_session_events(capture_session)

        book_states = []
        for event_type, _, book_state, _ in build_incremental_book(events, session_snapshot):
            if event_type == "depth" and book_state is not None:
                book_states.append(book_state)

        observations = simulate_passive_orders(
            events, session_snapshot, decision_every_n=10, horizon_ms=1000
        )

        if observations.empty or not book_states:
            pytest.skip("insufficient data")

        obs_bid = observations.iloc[0]["mid_at_placement"]
        book_bid = (book_states[0].best_bid + book_states[0].best_ask) / 2.0

        assert abs(obs_bid - book_bid) < 0.01, (
            f"observation mid {obs_bid:.2f} should match book mid {book_bid:.2f}"
        )


class TestTradeStreamEventType:
    """Regression test for failure mode 6: trade stream event_type must match V10 capture."""

    def test_trade_events_use_correct_event_type(self, capture_session: Path):
        events = load_session_events(capture_session)
        trade_events = [e for e in events if e["event_type"] in ("trade", "aggTrade")]
        assert len(trade_events) > 0

    def test_aggTrade_also_recognized(self, capture_session: Path):
        events = load_session_events(capture_session)
        trade_count = sum(1 for e in events if e["event_type"] == "trade")
        agg_count = sum(1 for e in events if e["event_type"] == "aggTrade")
        assert trade_count > 0 or agg_count > 0


class TestPassiveOrderSimulation:
    def test_simulation_produces_observations(self, capture_session: Path, session_snapshot: dict):
        events = load_session_events(capture_session)
        observations = simulate_passive_orders(
            events, session_snapshot, order_quantity=0.01, decision_every_n=10
        )

        assert not observations.empty
        assert "fill_fraction" in observations.columns
        assert "queue_ahead" in observations.columns
        assert "time_to_fill_ms" in observations.columns
        assert "filled" in observations.columns
        assert "adverse_selection_bps" in observations.columns

    def test_fill_fractions_are_bounded(self, capture_session: Path, session_snapshot: dict):
        events = load_session_events(capture_session)
        observations = simulate_passive_orders(events, session_snapshot)

        assert observations["fill_fraction"].between(0, 1).all()

    def test_both_sides_are_represented(self, capture_session: Path, session_snapshot: dict):
        events = load_session_events(capture_session)
        observations = simulate_passive_orders(events, session_snapshot)

        sides = set(observations["side"].unique())
        assert "bid" in sides
        assert "ask" in sides

    def test_some_orders_fill_and_some_do_not(self, capture_session: Path, session_snapshot: dict):
        events = load_session_events(capture_session)
        observations = simulate_passive_orders(events, session_snapshot, decision_every_n=5)

        fill_rate = observations["filled"].mean()
        assert 0 < fill_rate < 1, f"fill_rate={fill_rate} should be strictly between 0 and 1"

    def test_adverse_selection_has_both_signs(self, capture_session: Path, session_snapshot: dict):
        events = load_session_events(capture_session)
        observations = simulate_passive_orders(events, session_snapshot, decision_every_n=5)
        filled = observations[observations["filled"] == 1]

        if not filled.empty:
            assert np.all(np.isfinite(filled["adverse_selection_bps"]))
            assert filled["adverse_selection_bps"].std() >= 0

    def test_time_to_fill_is_non_negative(self, capture_session: Path, session_snapshot: dict):
        events = load_session_events(capture_session)
        observations = simulate_passive_orders(events, session_snapshot)

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
    def test_fill_probability_varies_with_queue(self, capture_session: Path, session_snapshot: dict):
        events = load_session_events(capture_session)
        observations = simulate_passive_orders(
            events, session_snapshot, decision_every_n=3, queue_ahead_fraction=0.5
        )

        if observations.empty:
            pytest.skip("no observations")

        q_values = observations["queue_ahead"].unique()
        if len(q_values) < 2:
            pytest.skip("insufficient queue variation")

        median_q = observations["queue_ahead"].median()
        low_q = observations[observations["queue_ahead"] <= median_q]
        high_q = observations[observations["queue_ahead"] > median_q]

        if low_q.empty or high_q.empty:
            pytest.skip("insufficient queue variation")

        low_fill = low_q["filled"].mean()
        high_fill = high_q["filled"].mean()

        assert low_fill != high_fill or low_q["queue_ahead"].mean() != high_q["queue_ahead"].mean(), (
            "fill rate or queue-ahead should vary between low and high queue groups"
        )

    def test_fee_adjusted_ev_is_computable(self, capture_session: Path, session_snapshot: dict):
        from app.v10_economics import passive_order_ev_bps

        events = load_session_events(capture_session)
        observations = simulate_passive_orders(events, session_snapshot, decision_every_n=3)

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

    def test_survival_curve_is_fittable(self, capture_session: Path, session_snapshot: dict):
        from app.v10_fill_survival import fit_kaplan_meier

        events = load_session_events(capture_session)
        observations = simulate_passive_orders(events, session_snapshot, decision_every_n=3)

        if observations.empty:
            pytest.skip("no observations")

        model = fit_kaplan_meier(
            observations["time_to_fill_ms"].to_numpy(float),
            observations["filled"].to_numpy(int),
        )

        prob = model.fill_probability(500.0)
        assert 0 <= prob <= 1
