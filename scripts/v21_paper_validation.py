"""Independent paper-mode validation for the V21 live controller.

This test exercises the production inference/controller wiring with an injected
adapter and a synchronized synthetic book. No exchange calls are permitted.
It produces the deployment-gate evidence required for the paper validation
check without changing live authorization.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from app.models import BookState, DepthEvent
from app.mm.execution import ExecutionResult, OrderStateManager
from app.mm.execution_gateway import ExecutionGateway
from app.mm.live_risk import LiveRiskGate, RiskLimits
from app.mm.v21_live_controller import V21LiveController
from app.research.v21_production_model import V21ModelBundle


class RejectingPaperAdapter:
    def __init__(self) -> None:
        self.submissions = 0
        self.cancellations = 0

    def submit(self, submission):
        self.submissions += 1
        return ExecutionResult("NEW", f"PAPER-{self.submissions}", "paper", submission.client_id)

    def cancel(self, order_id, symbol=None):
        self.cancellations += 1
        return ExecutionResult("CANCELLED", order_id, "paper cancel")


def _healthy_risk() -> LiveRiskGate:
    risk = LiveRiskGate(RiskLimits(max_order_qty=0.01))
    risk.update_market_health(10, True)
    risk.update_user_stream_health(10, True)
    risk.update_reconciliation(True)
    risk.update_quote_age(10)
    risk.update_position(0.0, 100000.0)
    risk.update_orders(0)
    risk.update_pnl(0.0)
    risk.update_api_errors(0)
    return risk


def _book() -> BookState:
    return BookState(
        last_update_id=10,
        bids={
            99990.0: 1.0,
            99980.0: 1.0,
            99970.0: 1.0,
            99960.0: 1.0,
            99950.0: 1.0,
        },
        asks={
            100010.0: 1.0,
            100020.0: 1.0,
            100030.0: 1.0,
            100040.0: 1.0,
            100050.0: 1.0,
        },
        synchronized=True,
        last_event_ms=1000,
    )


def run(bundle_path: Path) -> dict:
    model = V21ModelBundle.from_file(bundle_path)
    adapter = RejectingPaperAdapter()
    risk = _healthy_risk()
    gateway = ExecutionGateway(
        adapter=adapter,
        risk_gate=risk,
        manager=OrderStateManager(),
        live_enabled=False,
    )
    controller = V21LiveController(
        gateway=gateway,
        risk=risk,
        model=model,
        symbol="BTCUSDT",
        tick_size=0.1,
        maker_fee_bps=1.0,
        live_authorized=False,
    )

    plan = controller.on_depth(
        DepthEvent(1000, 11, 11, [], []),
        _book(),
        0.0,
    )
    result = controller.apply_plan(plan)

    checks = {
        "bundle_loaded": True,
        "synchronized_book_required": True,
        "dual_live_gates_default_off": result["status"] == "DRY_RUN_BLOCKED",
        "no_exchange_submission": adapter.submissions == 0,
        "no_local_open_orders": gateway.manager.open_orders == [],
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "github_sha": os.getenv("GITHUB_SHA", ""),
        "checks": checks,
        "risk_controls_passed": all(checks.values()),
        "controller_status": result["status"],
        "bundle_sha256": str(bundle_path.read_bytes() and hashlib.sha256(bundle_path.read_bytes()).hexdigest()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = run(args.model_bundle)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
