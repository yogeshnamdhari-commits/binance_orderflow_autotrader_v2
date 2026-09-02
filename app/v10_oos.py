"""Strict chronological walk-forward OOS evaluation for V10 execution research.

This module deliberately evaluates whole capture sessions chronologically:
for test session i, calibration uses only sessions < i. Test outcomes never
enter calibration for the same fold or any earlier fold. The module is
research-only and contains no order-placement logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from app.v10_empirical_adapter import (
    load_session_events,
    load_session_snapshot,
    simulate_passive_orders,
)
from app.v10_execution_research import evaluate_execution_fold


class OOSGateError(ValueError):
    """Raised when chronological OOS prerequisites are not satisfied."""


@dataclass(frozen=True)
class OOSConfig:
    """Frozen evaluation configuration; OOS data cannot modify these values."""

    min_train_observations: int = 100
    min_test_observations: int = 50
    order_quantity: float = 0.01
    decision_every_n: int = 10
    horizon_ms: int = 1000
    bins: tuple[float, ...] = (0.0, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, float("inf"))
    survival_horizon: float = 1000.0
    spread_capture_bps: float = 2.0
    fee_rebate_bps: float = 0.5
    inventory_cost_bps: float = 0.2
    exit_cost_bps: float = 0.3
    cancellation_cost_bps: float = 0.05
    min_positive_fold_fraction: float = 0.5
    require_positive_realized_ev: bool = True


@dataclass
class SessionValidation:
    session_id: str
    session_dir: str
    observations: pd.DataFrame
    start: pd.Timestamp | None
    end: pd.Timestamp | None
    valid: bool = True
    reason: str | None = None

    @property
    def n_observations(self) -> int:
        return int(len(self.observations))


@dataclass
class OOSResult:
    gate_pass: bool
    n_folds: int
    total_oos_observations: int
    n_positive_folds: int
    positive_fold_fraction: float
    mean_oos_realized_ev_bps: float
    min_fold_realized_ev_bps: float
    folds: list[dict[str, Any]] = field(default_factory=list)


def _session_id(session_dir: Path) -> str:
    manifest = session_dir / "manifest.json"
    if manifest.is_file():
        try:
            import json
            data = json.loads(manifest.read_text(encoding="utf-8"))
            value = data.get("session_id")
            if value:
                return str(value)
        except (OSError, ValueError, TypeError):
            pass
    return session_dir.name


def _normalize_observations(observations: pd.DataFrame) -> pd.DataFrame:
    if observations.empty:
        return observations.copy()
    out = observations.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    if out["timestamp"].duplicated().any():
        # Two sides can legitimately share a placement timestamp. Preserve
        # those rows; chronological validation is based on session bounds.
        out = out.sort_values(["timestamp", "side"]).reset_index(drop=True)
    else:
        out = out.sort_values("timestamp").reset_index(drop=True)
    if not out["timestamp"].is_monotonic_increasing:
        raise OOSGateError("observations are not chronologically ordered")
    required = {"side", "fill_fraction", "queue_ahead", "filled", "time_to_fill_ms", "adverse_selection_bps", "mid_at_placement", "post_mid"}
    missing = required - set(out.columns)
    if missing:
        raise OOSGateError(f"session observations missing columns: {sorted(missing)}")
    if not out["timestamp"].notna().all():
        raise OOSGateError("session observations contain invalid timestamps")
    return out


def validate_session(session_dir: str | Path, config: OOSConfig | None = None) -> SessionValidation:
    """Validate one captured session and produce its frozen observations."""
    config = config or OOSConfig()
    path = Path(session_dir)
    if not path.is_dir():
        raise OOSGateError(f"session directory does not exist: {path}")

    events = load_session_events(path)
    if not events:
        raise OOSGateError(f"session has no valid events: {path}")

    snapshot = load_session_snapshot(path)
    if snapshot is None:
        raise OOSGateError(f"session has no validated snapshot: {path}")

    observations = simulate_passive_orders(
        events,
        snapshot,
        order_quantity=config.order_quantity,
        decision_every_n=config.decision_every_n,
        horizon_ms=config.horizon_ms,
    )
    observations = _normalize_observations(observations)
    if observations.empty:
        raise OOSGateError(f"session produced no execution observations: {path}")

    return SessionValidation(
        session_id=_session_id(path),
        session_dir=str(path),
        observations=observations,
        start=observations["timestamp"].min(),
        end=observations["timestamp"].max(),
    )


def verify_chronology(sessions: Sequence[SessionValidation]) -> None:
    """Require strictly chronological, non-overlapping session intervals."""
    if not sessions:
        raise OOSGateError("at least one session is required")
    previous: SessionValidation | None = None
    for current in sessions:
        if current.start is None or current.end is None:
            raise OOSGateError(f"session has no time bounds: {current.session_id}")
        if current.start > current.end:
            raise OOSGateError(f"invalid session interval: {current.session_id}")
        if previous is not None:
            if current.start <= previous.end:
                raise OOSGateError(
                    "sessions must be strictly chronological and non-overlapping: "
                    f"{previous.session_id} -> {current.session_id}"
                )
        previous = current


def _fold_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["time_to_fill"] = out["time_to_fill_ms"].astype(float)
    out["filled"] = out["filled"].astype(int)
    return out


def _fold_economic_result(train: pd.DataFrame, test: pd.DataFrame, config: OOSConfig) -> dict[str, Any]:
    result = evaluate_execution_fold(
        _fold_frame(train),
        _fold_frame(test),
        bins=config.bins,
        survival_horizon=config.survival_horizon,
        spread_capture_bps=config.spread_capture_bps,
        fee_rebate_bps=config.fee_rebate_bps,
        inventory_cost_bps=config.inventory_cost_bps,
        exit_cost_bps=config.exit_cost_bps,
        cancellation_cost_bps=config.cancellation_cost_bps,
    )
    return result


def evaluate_sessions(
    session_dirs: Sequence[str | Path],
    *,
    config: OOSConfig | None = None,
) -> OOSResult:
    """Run session-level expanding-window chronological OOS evaluation.

    Session 0 is calibration-only. Session 1 is the first untouched OOS test
    using only session 0. Session 2 uses sessions 0+1 for calibration, and so
    on. The OOS sessions are never appended to a training set before their own
    fold is evaluated.
    """
    config = config or OOSConfig()
    if config.min_train_observations <= 0 or config.min_test_observations <= 0:
        raise OOSGateError("minimum observations must be positive")
    if not 0.0 <= config.min_positive_fold_fraction <= 1.0:
        raise OOSGateError("min_positive_fold_fraction must be in [0,1]")
    if config.horizon_ms <= 0 or config.decision_every_n <= 0:
        raise OOSGateError("horizon_ms and decision_every_n must be positive")

    if len(session_dirs) < 2:
        raise OOSGateError("at least two chronological sessions are required for OOS")

    validations = [validate_session(path, config=config) for path in session_dirs]
    verify_chronology(validations)

    folds: list[dict[str, Any]] = []
    for i in range(1, len(validations)):
        train_parts = [v.observations for v in validations[:i]]
        train = pd.concat(train_parts, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
        test = validations[i].observations.copy().sort_values("timestamp").reset_index(drop=True)

        if len(train) < config.min_train_observations:
            raise OOSGateError(
                f"training observations below minimum before {validations[i].session_id}: "
                f"{len(train)} < {config.min_train_observations}"
            )
        if len(test) < config.min_test_observations:
            raise OOSGateError(
                f"test observations below minimum in {validations[i].session_id}: "
                f"{len(test)} < {config.min_test_observations}"
            )
        if train["timestamp"].max() >= test["timestamp"].min():
            raise OOSGateError(f"training data overlaps test data in {validations[i].session_id}")

        fold = _fold_economic_result(train, test, config)
        fold.update({
            "session_id": validations[i].session_id,
            "train_sessions": i,
            "train_observations": int(len(train)),
            "train_start": train["timestamp"].min(),
            "train_end": train["timestamp"].max(),
            "test_start": test["timestamp"].min(),
            "test_end": test["timestamp"].max(),
        })
        folds.append(fold)

    if not folds:
        raise OOSGateError("no OOS folds were produced")

    positive = sum(1 for f in folds if float(f["mean_oos_realized_ev_bps"]) > 0.0)
    positive_fraction = positive / len(folds)
    total_orders = sum(int(f["oos_orders"]) for f in folds)
    weighted_mean = sum(
        float(f["mean_oos_realized_ev_bps"]) * int(f["oos_orders"]) for f in folds
    ) / total_orders
    min_ev = min(float(f["mean_oos_realized_ev_bps"]) for f in folds)

    gate_pass = positive_fraction >= config.min_positive_fold_fraction
    if config.require_positive_realized_ev:
        gate_pass = gate_pass and weighted_mean > 0.0

    return OOSResult(
        gate_pass=bool(gate_pass),
        n_folds=len(folds),
        total_oos_observations=total_orders,
        n_positive_folds=positive,
        positive_fold_fraction=float(positive_fraction),
        mean_oos_realized_ev_bps=float(weighted_mean),
        min_fold_realized_ev_bps=float(min_ev),
        folds=folds,
    )
