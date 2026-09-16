from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import config_sha256


@dataclass(frozen=True)
class ProductionReadiness:
    ready: bool
    reasons: tuple[str, ...]
    git_commit: str
    config_sha256: str


def evaluate_readiness(
    *,
    git_commit: str,
    config_path: str,
    expected_config_sha256: str | None,
    live_order_submission: bool,
    market_ready: bool,
    user_stream_ready: bool,
    reconciled: bool,
    risk_ready: bool,
    tests_passed: bool,
) -> ProductionReadiness:
    reasons: list[str] = []
    path = Path(config_path)
    if not path.is_file():
        reasons.append("missing_config")
        actual_hash = "missing"
    else:
        actual_hash = config_sha256(config_path)
        if expected_config_sha256 and actual_hash != expected_config_sha256:
            reasons.append("config_hash_mismatch")
    if not git_commit or git_commit == "unknown":
        reasons.append("git_commit_unknown")
    if not market_ready:
        reasons.append("market_data_not_ready")
    if not user_stream_ready:
        reasons.append("user_stream_not_ready")
    if not reconciled:
        reasons.append("state_not_reconciled")
    if not risk_ready:
        reasons.append("risk_not_ready")
    if not tests_passed:
        reasons.append("validation_tests_failed")
    # Live order submission is intentionally a separate deployment decision.
    if live_order_submission:
        reasons.append("live_submission_requires_explicit_deployment_gate")

    return ProductionReadiness(
        ready=not reasons,
        reasons=tuple(reasons),
        git_commit=git_commit,
        config_sha256=actual_hash,
    )
