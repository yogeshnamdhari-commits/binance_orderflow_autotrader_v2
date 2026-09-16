"""End-to-end V10 forward validation pipeline.

This module orchestrates the complete forward validation workflow:
1. Verify frozen model is loaded
2. Load forward session(s) and verify temporal independence
3. Run capture integrity audit
4. Run frozen forward validator
5. Produce execution-cost decomposition report
6. Produce regime-level performance analysis
7. Produce final PASS/FAIL decision

No model updates occur during forward validation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .v10_data_audit import audit_session
from .v10_empirical_adapter import load_session_events, load_session_snapshot, simulate_passive_orders
from .v10_forward_validator import (
    ForwardGateStatus,
    FrozenModelConfig,
    V10ForwardValidator,
    freeze_and_export_model,
    run_forward_validation,
)


OOS_CUTOFF_START_NS = 1788395843660664000

FROZEN_CONFIG = FrozenModelConfig(
    bins=(0.0, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, float("inf")),
    survival_horizon=1000.0,
    spread_capture_bps=2.0,
    fee_rebate_bps=0.5,
    inventory_cost_bps=0.2,
    exit_cost_bps=0.3,
    cancellation_cost_bps=0.05,
    order_quantity=0.01,
    decision_every_n=10,
    horizon_ms=1000,
)


@dataclass
class ForwardPipelineResult:
    status: str
    forward_sessions: list[str]
    temporal_independence_verified: bool
    capture_audit_passed: list[str]
    capture_audit_failed: list[str]
    n_forward_observations: int
    forward_result: dict[str, Any] | None
    execution_cost_report: dict[str, Any]
    regime_report: dict[str, Any]
    frozen_model_exported: bool
    error: str | None


def verify_temporal_independence(session_dirs: list[Path]) -> tuple[bool, list[str]]:
    """Verify sessions start after OOS cutoff."""
    forward_sessions = []
    for d in session_dirs:
        manifest_path = d / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            start_ns = int(manifest.get("start_ns", 0))
            if start_ns > OOS_CUTOFF_START_NS:
                forward_sessions.append(d.name)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return len(forward_sessions) > 0, forward_sessions


def run_forward_pipeline(
    forward_session_dirs: list[str | Path],
    train_observations: pd.DataFrame,
    oos_ev_bps: float = 0.1854,
    oos_fill_rate: float = 0.1324,
    oos_adverse_bps: float = 0.0,
    output_path: str | Path | None = None,
) -> ForwardPipelineResult:
    """Run complete forward validation pipeline.

    Args:
        forward_session_dirs: Directories containing forward session data
        train_observations: Training observations for frozen model
        oos_ev_bps: OOS EV benchmark for drift comparison
        oos_fill_rate: OOS fill rate benchmark
        oos_adverse_bps: OOS adverse selection benchmark
        output_path: Optional path to write results JSON

    Returns:
        ForwardPipelineResult with all metrics and PASS/FAIL decision
    """
    forward_session_dirs = [Path(d) for d in forward_session_dirs]

    temporal_ok, forward_sessions = verify_temporal_independence(forward_session_dirs)

    capture_pass = []
    capture_fail = []
    all_observations = []

    for d in forward_session_dirs:
        if d.name not in forward_sessions:
            continue
        audit = audit_session(d)
        if audit["overall_pass"]:
            capture_pass.append(d.name)
        else:
            capture_fail.append(d.name)
            continue
        try:
            events = load_session_events(d)
            snapshot = load_session_snapshot(d)
            if not events or snapshot is None:
                capture_fail.append(d.name)
                continue
            obs = simulate_passive_orders(
                events,
                snapshot,
                order_quantity=FROZEN_CONFIG.order_quantity,
                decision_every_n=FROZEN_CONFIG.decision_every_n,
                horizon_ms=FROZEN_CONFIG.horizon_ms,
            )
            if not obs.empty:
                all_observations.append(obs)
        except Exception:
            capture_fail.append(d.name)

    forward_obs = pd.concat(all_observations, ignore_index=True) if all_observations else pd.DataFrame()

    frozen_model_exported = False
    if output_path is not None:
        try:
            freeze_and_export_model(train_observations, FROZEN_CONFIG, Path(output_path) / "frozen_model.json")
            frozen_model_exported = True
        except Exception:
            pass

    forward_result = None
    if not forward_obs.empty:
        try:
            forward_result = run_forward_validation(
                train_observations=train_observations,
                forward_observations=forward_obs,
                frozen_config=FROZEN_CONFIG,
                oos_fill_rate=oos_fill_rate,
                oos_ev_bps=oos_ev_bps,
                oos_adverse_bps=oos_adverse_bps,
            )
            forward_result_dict = {
                "status": forward_result.status.value,
                "n_orders": forward_result.n_orders,
                "n_filled": forward_result.n_filled,
                "fill_rate": forward_result.fill_rate,
                "mean_predicted_fill_probability": forward_result.mean_predicted_fill_probability,
                "mean_actual_fill_fraction": forward_result.mean_actual_fill_fraction,
                "fill_prediction_error": forward_result.fill_prediction_error,
                "mean_predicted_ev_bps": forward_result.mean_predicted_ev_bps,
                "mean_realized_ev_bps": forward_result.mean_realized_ev_bps,
                "ev_prediction_error": forward_result.ev_prediction_error,
                "mean_spread_bps": forward_result.mean_spread_bps,
                "mean_slippage_bps": forward_result.mean_slippage_bps,
                "mean_fees_bps": forward_result.mean_fees_bps,
                "mean_adverse_selection_bps": forward_result.mean_adverse_selection_bps,
                "calibration_drift_fill": forward_result.calibration_drift_fill,
                "calibration_drift_ev": forward_result.calibration_drift_ev,
                "forward_gate": forward_result.forward_gate,
                "gate_conditions": forward_result.gate_conditions,
                "regime_results": forward_result.regime_results,
            }
            forward_result = forward_result_dict
        except Exception as e:
            forward_result = {"error": str(e)}

    execution_cost_report = {}
    if forward_result and "error" not in forward_result:
        execution_cost_report = {
            "gross_model_edge_bps": oos_ev_bps,
            "realized_forward_ev_bps": forward_result.get("mean_realized_ev_bps", 0.0),
            "execution_cost_impact_bps": oos_ev_bps - forward_result.get("mean_realized_ev_bps", 0.0),
            "spread_cost_bps": forward_result.get("mean_spread_bps", 0.0),
            "slippage_cost_bps": forward_result.get("mean_slippage_bps", 0.0),
            "fee_cost_bps": forward_result.get("mean_fees_bps", 0.0),
            "adverse_selection_cost_bps": forward_result.get("mean_adverse_selection_bps", 0.0),
            "fill_rate_vs_expected": forward_result.get("fill_prediction_error", 0.0),
            "ev_vs_expected": forward_result.get("ev_prediction_error", 0.0),
        }

    regime_report = {}
    if forward_result and "regime_results" in forward_result:
        regime_report = forward_result.get("regime_results", {})

    status = "PASS" if forward_result and forward_result.get("forward_gate", False) else "FAIL"
    if not temporal_ok:
        status = "BLOCKED_NO_FORWARD_DATA"
    elif not forward_sessions:
        status = "BLOCKED_NO_TEMPORAL_INDEPENDENCE"

    result = ForwardPipelineResult(
        status=status,
        forward_sessions=forward_sessions,
        temporal_independence_verified=temporal_ok,
        capture_audit_passed=capture_pass,
        capture_audit_failed=capture_fail,
        n_forward_observations=len(forward_obs),
        forward_result=forward_result,
        execution_cost_report=execution_cost_report,
        regime_report=regime_report,
        frozen_model_exported=frozen_model_exported,
        error=None if forward_sessions else "No temporally independent forward sessions found",
    )

    if output_path is not None and forward_result:
        try:
            output = Path(output_path)
            output.mkdir(parents=True, exist_ok=True)
            result_dict = {
                "schema_version": "v10.forward.pipeline.v1",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "oos_reference_ev_bps": oos_ev_bps,
                "oos_reference_fill_rate": oos_fill_rate,
                "oos_cutoff_start_ns": OOS_CUTOFF_START_NS,
                "status": result.status,
                "temporal_independence_verified": result.temporal_independence_verified,
                "forward_sessions": result.forward_sessions,
                "capture_audit_passed": result.capture_audit_passed,
                "capture_audit_failed": result.capture_audit_failed,
                "n_forward_observations": result.n_forward_observations,
                "forward_result": result.forward_result,
                "execution_cost_report": result.execution_cost_report,
                "regime_report": result.regime_report,
            }
            (output / "forward_pipeline_results.json").write_text(
                json.dumps(result_dict, indent=2, default=str)
            )
        except Exception:
            pass

    return result


def discover_sessions(data_dir: Path) -> list[Path]:
    """Discover all V10 capture sessions in a directory."""
    if not data_dir.is_dir():
        return []
    sessions = []
    for d in data_dir.iterdir():
        if d.is_dir() and (d / "events.jsonl").is_file() and (d / "manifest.json").is_file():
            sessions.append(d)
    return sorted(sessions, key=lambda p: json.loads((p / "manifest.json").read_text()).get("start_ns", 0))


def get_forward_sessions(data_dir: Path, cutoff_ns: int = OOS_CUTOFF_START_NS) -> list[Path]:
    """Get sessions that start after the OOS cutoff."""
    return [d for d in discover_sessions(data_dir) if json.loads((d / "manifest.json").read_text()).get("start_ns", 0) > cutoff_ns]


__all__ = [
    "FROZEN_CONFIG",
    "OOS_CUTOFF_START_NS",
    "ForwardPipelineResult",
    "freeze_and_export_model",
    "run_forward_pipeline",
    "verify_temporal_independence",
    "discover_sessions",
    "get_forward_sessions",
]
