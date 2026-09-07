"""Fail-closed production authorization policy.

This gate is intentionally independent from model predictions. A strategy can
be technically operational while remaining economically unauthorized.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Evidence:
    data_integrity: bool
    model_frozen: bool
    independent_forward: bool
    execution_cost_validated: bool
    robustness: bool
    statistical_significance: bool
    paper_validated: bool
    risk_controls: bool


REQUIRED = (
    "data_integrity", "model_frozen", "independent_forward",
    "execution_cost_validated", "robustness", "statistical_significance",
    "paper_validated", "risk_controls",
)


def authorize_live(evidence: Evidence, *, explicit_authorization: bool = False) -> tuple[bool, list[str]]:
    """Return (authorized, failed_gates). Any missing gate blocks live trading."""
    failed = [name for name in REQUIRED if not getattr(evidence, name)]
    if not explicit_authorization:
        failed.append("explicit_authorization")
    return (len(failed) == 0, failed)
