from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .execution import ExecutionResult, OrderStateManager
from .live_risk import LiveRiskGate


@dataclass(frozen=True)
class Submission:
    symbol: str
    side: str
    qty: float
    price: float
    client_id: str


class ExecutionAdapter(Protocol):
    def submit(self, submission: Submission) -> ExecutionResult: ...
    def cancel(self, order_id: str) -> ExecutionResult: ...


class ExecutionGateway:
    """Single fail-closed boundary between strategy and exchange execution."""

    def __init__(
        self,
        adapter: ExecutionAdapter,
        risk_gate: LiveRiskGate,
        manager: OrderStateManager,
        live_enabled: bool = False,
    ) -> None:
        self.adapter = adapter
        self.risk_gate = risk_gate
        self.manager = manager
        self.live_enabled = bool(live_enabled)

    def submit(self, submission: Submission) -> ExecutionResult:
        allowed, reasons = self.risk_gate.can_submit(submission.qty)
        if not allowed:
            return ExecutionResult(
                status="BLOCKED_RISK",
                order_id=None,
                message=";".join(reasons),
                client_id=submission.client_id,
            )

        if self.manager.duplicate(submission.client_id):
            return ExecutionResult(
                status="REJECTED_DUPLICATE",
                order_id=None,
                message="duplicate client id",
                client_id=submission.client_id,
            )

        if not self.live_enabled:
            return ExecutionResult(
                status="BLOCKED_LIVE_DISABLED",
                order_id=None,
                message="live order submission is disabled",
                client_id=submission.client_id,
            )

        return self.adapter.submit(submission)

    def cancel(self, order_id: str) -> ExecutionResult:
        order = self.manager.get(order_id)
        if order is None:
            return ExecutionResult("REJECTED_UNKNOWN_ORDER", None, "unknown order")
        return self.adapter.cancel(order_id)
