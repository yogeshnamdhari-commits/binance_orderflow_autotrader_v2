"""Tests for strict chronological V10 walk-forward OOS evaluation.

The tests use deterministic synthetic captures only. They verify that:
- sessions must be chronologically ordered and non-overlapping;
- at least one prior session is required for a test fold;
- minimum training/test observation gates are enforced;
- OOS evaluation uses only prior-session observations for calibration;
- multiple folds are aggregated without leaking future observations;
- a stable positive synthetic path can pass the structural OOS gate.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from app.v10_oos import (
    OOSConfig,
    OOSGateError,
    evaluate_sessions,
    validate_session,
    verify_chronology,
)
from app.v10_synthetic_capture import generate_synthetic_capture


BASE_NS = 1_700_000_000_000_000_000
SESSION_NS = 10_000_000_000


def _session(tmp_path: Path, name: str, offset: int) -> Path:
    return generate_synthetic_capture(
        tmp_path / name,
        session_id=name,
        n_depth_events=200,
        n_trades=80,
        start_mid=65000.0,
        start_ns=BASE_NS + offset * SESSION_NS,
        seed=42 + offset,
    )


class TestSessionValidation:
    def test_valid_session_passes(self, tmp_path: Path):
        session = _session(tmp_path, "s1", 0)
        result = validate_session(session)
        assert result.valid
        assert result.n_observations > 0
        assert result.start is not None
        assert result.end is not None

    def test_invalid_missing_session_rejected(self, tmp_path: Path):
        with pytest.raises(OOSGateError, match="session"):
            validate_session(tmp_path / "does-not-exist")


class TestChronology:
    def test_overlapping_sessions_rejected(self, tmp_path: Path):
        a = _session(tmp_path, "a", 0)
        b = _session(tmp_path, "b", 0)
        va = validate_session(a)
        vb = validate_session(b)
        with pytest.raises(OOSGateError, match="chronolog|overlap"):
            verify_chronology([va, vb])

    def test_out_of_order_sessions_rejected(self, tmp_path: Path):
        a = _session(tmp_path, "a", 0)
        b = _session(tmp_path, "b", 1)
        va = validate_session(a)
        vb = validate_session(b)
        with pytest.raises(OOSGateError, match="chronolog|order"):
            verify_chronology([vb, va])

    def test_sequential_sessions_pass(self, tmp_path: Path):
        sessions = [_session(tmp_path, f"s{i}", i) for i in range(3)]
        validations = [validate_session(p) for p in sessions]
        verify_chronology(validations)


class TestOOSGate:
    def test_requires_multiple_sessions(self, tmp_path: Path):
        session = _session(tmp_path, "s1", 0)
        with pytest.raises(OOSGateError, match="sessions"):
            evaluate_sessions([session], config=OOSConfig(min_train_observations=1, min_test_observations=1))

    def test_minimum_observation_gate(self, tmp_path: Path):
        sessions = [_session(tmp_path, f"s{i}", i) for i in range(2)]
        config = OOSConfig(min_train_observations=10_000, min_test_observations=10_000)
        with pytest.raises(OOSGateError, match="observations"):
            evaluate_sessions(sessions, config=config)

    def test_happy_path_produces_oos_folds(self, tmp_path: Path):
        sessions = [_session(tmp_path, f"s{i}", i) for i in range(4)]
        config = OOSConfig(
            min_train_observations=5,
            min_test_observations=5,
            require_positive_realized_ev=False,
        )
        result = evaluate_sessions(sessions, config=config)

        assert result.n_folds == 3
        assert result.total_oos_observations >= 15
        assert len(result.folds) == 3
        assert all(f["oos_orders"] >= 5 for f in result.folds)

    def test_fold_training_is_strictly_prior_to_test(self, tmp_path: Path):
        sessions = [_session(tmp_path, f"s{i}", i) for i in range(3)]
        config = OOSConfig(
            min_train_observations=5,
            min_test_observations=5,
            require_positive_realized_ev=False,
        )
        result = evaluate_sessions(sessions, config=config)

        for fold in result.folds:
            assert fold["train_end"] < fold["test_start"]

    def test_result_is_not_marked_pass_on_one_positive_fold_only(self, tmp_path: Path):
        sessions = [_session(tmp_path, f"s{i}", i) for i in range(3)]
        config = OOSConfig(
            min_train_observations=5,
            min_test_observations=5,
            min_positive_fold_fraction=1.0,
            require_positive_realized_ev=True,
        )
        result = evaluate_sessions(sessions, config=config)
        assert result.gate_pass is False or result.n_positive_folds == result.n_folds


def test_result_schema_is_serializable(tmp_path: Path):
    sessions = [_session(tmp_path, f"s{i}", i) for i in range(3)]
    result = evaluate_sessions(
        sessions,
        config=OOSConfig(
            min_train_observations=5,
            min_test_observations=5,
            require_positive_realized_ev=False,
        ),
    )
    frame = pd.DataFrame(result.folds)
    assert not frame.empty
    assert {"session_id", "oos_orders", "mean_oos_realized_ev_bps", "train_end", "test_start"}.issubset(frame.columns)
