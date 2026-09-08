"""Fail-closed production preflight for the V16 BTCUSDT order-flow system.

This module validates deployment prerequisites without ever enabling live order
submission. It is intentionally independent from the research gate so that a
future execution adapter cannot accidentally bypass the deployment checks.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PreflightResult:
    ready: bool
    live_order_submission: bool
    checks: dict[str, str]


class ProductionPreflight:
    """Evaluate production prerequisites and fail closed on any uncertainty."""

    def __init__(
        self,
        root: Path | str = ".",
        *,
        live_order_submission: bool = False,
        production_authorized: bool = False,
    ) -> None:
        self.root = Path(root)
        self.live_order_submission = bool(live_order_submission)
        self.production_authorized = bool(production_authorized)

    def _load_json(self, path: Path) -> dict[str, Any] | None:
        try:
            return json.loads(path.read_text()) if path.exists() else None
        except (OSError, json.JSONDecodeError):
            return None

    def evaluate(self) -> PreflightResult:
        checks: dict[str, str] = {}

        # Explicit authorization is required, but it is never sufficient alone.
        checks["explicit_authorization"] = (
            "PASS" if self.production_authorized else "FAIL"
        )

        paper = self._load_json(
            self.root / "archive" / "v16" / "v16_paper_trading_result.json"
        )
        paper_ok = bool(
            paper
            and paper.get("paper_trading_passed") is True
            and float(paper.get("net_ev_bps", 0.0)) > 0.0
            and int(paper.get("n_trades", 0)) >= 100
        )
        checks["paper_trading"] = "PASS" if paper_ok else "FAIL"

        # The frozen models must exist before a deployment can be considered.
        archive = self.root / "archive" / "v16"
        return_model = archive / "v16_frozen_return_model.joblib"
        fill_model = archive / "v16_frozen_fill_model.joblib"
        checks["frozen_models"] = (
            "PASS" if return_model.is_file() and fill_model.is_file() else "FAIL"
        )

        # Production must have a recorded gate result rather than relying on
        # an in-memory assertion from a previous process.
        gate = self._load_json(self.root / "data" / "evidence" / "v16_production_gate.json")
        checks["production_gate_record"] = "PASS" if gate else "FAIL"

        # Fail closed unless live submission is explicitly and independently
        # enabled. This preflight itself never changes the flag.
        checks["live_order_submission"] = (
            "PASS" if self.live_order_submission else "FAIL"
        )

        # A production preflight must never claim readiness while live order
        # submission is disabled. This protects paper/simulation runtimes from
        # being mistaken for an executable trading deployment.
        ready = all(value == "PASS" for value in checks.values())
        if not self.live_order_submission:
            ready = False

        return PreflightResult(
            ready=ready,
            live_order_submission=self.live_order_submission,
            checks=checks,
        )
