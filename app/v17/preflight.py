"""Fail-closed production readiness checks for the frozen V16 system.

This module never enables live trading. It verifies that the immutable research,
paper-trading and safety evidence required before activation is present and
internally consistent. Exchange credentials and actual live execution remain
outside this preflight and must be verified operationally before activation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STATUS = ROOT / "FINAL_STATUS.json"
PAPER = ROOT / "data/evidence/v16_paper_trading.json"
REQUIRED = (
    ROOT / "archive/v16/v16_frozen_return_model.joblib",
    ROOT / "archive/v16/v16_frozen_fill_model.joblib",
    ROOT / "data/evidence/v16_paper_trading.json",
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_preflight() -> dict[str, Any]:
    result: dict[str, Any] = {
        "system": "binance_orderflow_autotrader_v2",
        "model_version": "V16",
        "live_order_submission": False,
        "production_authorized": False,
        "checks": {},
        "status": "FAIL",
    }

    result["checks"]["required_artifacts"] = all(p.is_file() for p in REQUIRED)
    if not result["checks"]["required_artifacts"]:
        return result

    paper = _load(PAPER)
    status = _load(STATUS)
    result["checks"]["paper_complete"] = (
        paper.get("status") == "COMPLETE"
        and paper.get("paper_trading_passed") is True
        and int(paper.get("n_trades", 0)) > 0
        and paper.get("live_order_submitted") is False
    )

    # The status file historically contains contradictory legacy fields.  The
    # authoritative paper evidence must agree with the immutable safety state.
    result["checks"]["paper_status_consistent"] = (
        status.get("live_order_submission") is False
        and paper.get("live_order_submitted") is False
        and paper.get("paper_trading_passed") is True
    )
    result["paper_net_ev_bps"] = paper.get("net_ev_bps")
    result["paper_trades"] = paper.get("n_trades")

    # A positive paper result is necessary but never sufficient to authorize
    # live trading. Operational activation remains an explicit, separate step.
    result["checks"]["live_safety_lock"] = (
        status.get("production_authorized") is False
        and status.get("live_order_submission") is False
    )

    if all(result["checks"].values()):
        result["status"] = "READY_LOCKED"
    return result


if __name__ == "__main__":
    outcome = run_preflight()
    print(json.dumps(outcome, indent=2, sort_keys=True))
    raise SystemExit(0 if outcome["status"] == "READY_LOCKED" else 1)
