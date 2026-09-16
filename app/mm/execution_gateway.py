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
        self._exchange_to_local: dict[str, str] = {}

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

        local = self.manager.create(
            submission.symbol,
            submission.side,
            submission.qty,
            submission.price,
            submission.client_id,
        )
        if local is None:
            return ExecutionResult(
                status="REJECTED_DUPLICATE",
                order_id=None,
                message="duplicate client id",
                client_id=submission.client_id,
            )

        try:
            result = self.adapter.submit(submission)
        except Exception as exc:
            # Never retry automatically: a timeout can mean the exchange accepted
            # the order. Reconciliation must resolve the outcome first.
            self.manager.timeout_order(local.order_id, reason="submission_ambiguous")
            self.risk_gate.emergency_stop()
            return ExecutionResult(
                status="UNKNOWN_SUBMISSION",
                order_id=local.order_id,
                message=f"submission outcome unknown: {type(exc).__name__}",
                client_id=submission.client_id,
            )

        if result.order_id:
            self._exchange_to_local[str(result.order_id)] = local.order_id

        status = result.status.upper()
        if status in {"REJECTED", "EXPIRED", "CANCELED", "CANCELLED", "EXPIRED_IN_MATCH"}:
            self.manager.reject(local.order_id, reason=result.message)
        elif status in {"FILLED"}:
            self.manager.mark_filled(local.order_id, submission.price, submission.qty)
        return result

    def cancel(self, order_id: str) -> ExecutionResult:
        local_id = self._exchange_to_local.get(str(order_id), str(order_id))
        order = self.manager.get(local_id)
        if order is None:
            return ExecutionResult("REJECTED_UNKNOWN_ORDER", None, "unknown order")
        try:
            result = self.adapter.cancel(str(order_id))
        except Exception as exc:
            self.risk_gate.emergency_stop()
            return ExecutionResult("CANCEL_UNKNOWN", str(order_id), f"cancel outcome unknown: {type(exc).__name__}")
        status = result.status.upper()
        if status in {"CANCELED", "CANCELLED", "EXPIRED", "EXPIRED_IN_MATCH"}:
            self.manager.cancel(local_id)
        return result
