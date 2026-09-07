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
import json

import numpy as np
import pandas as pd

from .v10_data_audit import audit_session
from .v10_empirical_adapter import (
    load_session_events,
    load_session_snapshot,
    simulate_passive_orders,
)
from .v10_execution_research import evaluate_execution_fold


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
    regime: dict[str, Any] | None = None

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


def _compute_session_regime(
    session_dir: Path, events: list[dict[str, Any]], observations: pd.DataFrame
) -> dict[str, Any]:
    """Compute session-level regime descriptors from raw events and observations."""
    manifest = json.loads((session_dir / "manifest.json").read_text(encoding="utf-8"))
    start_ns = int(manifest.get("start_ns", 0))
    end_ns = int(manifest.get("end_ns", 0) or 0)
    duration_sec = (end_ns - start_ns) / 1e9 if end_ns > start_ns else 0.0

    depth_events = [e for e in events if e["event_type"] == "depthUpdate"]
    trade_events = [e for e in events if e["event_type"] in ("trade", "aggTrade")]

    mids: list[float] = []
    spreads: list[float] = []
    bid_sizes: list[float] = []
    ask_sizes: list[float] = []

    from .v10_empirical_adapter import build_incremental_book

    for _, _, book_state, _ in build_incremental_book(events, load_session_snapshot(session_dir)):
        if book_state is None:
            continue
        if book_state.best_bid > 0 and book_state.best_ask > book_state.best_bid:
            mid = (book_state.best_bid + book_state.best_ask) / 2.0
            mids.append(mid)
            spreads.append(book_state.best_ask - book_state.best_bid)
            bid_sizes.append(book_state.bid_size)
            ask_sizes.append(book_state.ask_size)

    trade_prices: list[float] = []
    for event in trade_events:
        data = event["payload"].get("data", event["payload"])
        try:
            trade_prices.append(float(data["p"]))
        except (KeyError, TypeError, ValueError):
            continue

    fill_rate = float(observations["filled"].mean()) if not observations.empty else 0.0
    n_fills = int(observations["filled"].sum())

    result: dict[str, Any] = {
        "session_id": manifest.get("session_id", session_dir.name),
        "start_ns": start_ns,
        "end_ns": end_ns,
        "duration_sec": duration_sec,
        "symbol": manifest.get("symbol", "UNKNOWN"),
        "n_events": len(events),
        "n_depth_events": len(depth_events),
        "n_trade_events": len(trade_events),
        "depth_event_rate_per_sec": len(depth_events) / duration_sec if duration_sec > 0 else 0.0,
        "trade_event_rate_per_sec": len(trade_events) / duration_sec if duration_sec > 0 else 0.0,
        "mid_price_mean": float(np.mean(mids)) if mids else float("nan"),
        "mid_price_std": float(np.std(mids)) if mids else float("nan"),
        "spread_mean_bps": float(np.mean(spreads) / np.mean(mids) * 10000) if mids and spreads else float("nan"),
        "spread_median_bps": float(np.median(spreads) / np.mean(mids) * 10000) if mids and spreads else float("nan"),
        "bid_size_mean": float(np.mean(bid_sizes)) if bid_sizes else float("nan"),
        "ask_size_mean": float(np.mean(ask_sizes)) if ask_sizes else float("nan"),
        "book_imbalance_mean": float(np.mean([(b - a) / (b + a) for b, a in zip(bid_sizes, ask_sizes) if b + a > 0])) if bid_sizes and ask_sizes else float("nan"),
        "book_imbalance_std": float(np.std([(b - a) / (b + a) for b, a in zip(bid_sizes, ask_sizes) if b + a > 0])) if bid_sizes and ask_sizes else float("nan"),
        "return_volatility_bps": (
            float(np.std(np.diff(np.log(np.array(trade_prices, dtype=float)))) * 10000)
            if len(trade_prices) > 1 and all(p > 0 for p in trade_prices)
            else float("nan")
        ),
        "n_observations": int(len(observations)),
        "n_fills": n_fills,
        "fill_rate": fill_rate,
        "mean_adverse_selection_bps": float(observations["adverse_selection_bps"].mean()) if not observations.empty else float("nan"),
    }
    return result


def _normalize_observations(observations: pd.DataFrame) -> pd.DataFrame:
    if observations.empty:
        return observations.copy()
    out = observations.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    if out["timestamp"].duplicated().any():
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

    audit = audit_session(path)
    if not audit["overall_pass"]:
        fail_reasons = [
            key for key in (
                "parse_integrity_pass",
                "timestamp_monotonicity_pass",
                "duplicate_raw_pass",
                "required_metadata_pass",
                "depth_continuity_pass",
                "snapshot_bridge_pass",
            ) if not audit.get(key, False)
        ]
        raise OOSGateError(
            f"session {path.name} failed capture-integrity audit: {', '.join(fail_reasons)}"
        )

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
        regime=_compute_session_regime(path, events, observations),
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
    out = out.rename(columns={"time_to_fill_ms": "time_to_fill"})
    out["time_to_fill"] = out["time_to_fill"].astype(float)
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
    """Run session-level expanding-window chronological OOS evaluation."""
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


__all__ = [
    "OOSConfig",
    "OOSGateError",
    "OOSResult",
    "SessionValidation",
    "evaluate_sessions",
    "validate_session",
    "verify_chronology",
]
