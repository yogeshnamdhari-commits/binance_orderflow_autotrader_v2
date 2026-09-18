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
    def cancel(self, order_id: str, symbol: str | None = None) -> ExecutionResult: ...


class ExecutionGateway:
    """Single fail-closed boundary between strategy and exchange execution."""

    def __init__(self, adapter: ExecutionAdapter, risk_gate: LiveRiskGate,
                 manager: OrderStateManager, live_enabled: bool = False) -> None:
        self.adapter = adapter
        self.risk_gate = risk_gate
        self.manager = manager
        self.live_enabled = bool(live_enabled)
        self._exchange_to_local: dict[str, str] = {}

    def submit(self, submission: Submission) -> ExecutionResult:
        allowed, reasons = self.risk_gate.can_submit(submission.qty)
        if not allowed:
            return ExecutionResult("BLOCKED_RISK", None, ";".join(reasons), submission.client_id)
        if self.manager.duplicate(submission.client_id):
            return ExecutionResult("REJECTED_DUPLICATE", None, "duplicate client id", submission.client_id)
        if not self.live_enabled:
            return ExecutionResult("BLOCKED_LIVE_DISABLED", None, "live order submission is disabled", submission.client_id)

        local = self.manager.create(submission.symbol, submission.side, submission.qty,
                                    submission.price, submission.client_id)
        if local is None:
            return ExecutionResult("REJECTED_DUPLICATE", None, "duplicate client id", submission.client_id)

        try:
            result = self.adapter.submit(submission)
        except Exception as exc:
            self.manager.timeout_order(local.order_id, reason="submission_ambiguous")
            self.risk_gate.emergency_stop()
            return ExecutionResult("UNKNOWN_SUBMISSION", local.order_id,
                                   f"submission outcome unknown: {type(exc).__name__}", submission.client_id)

        if result.order_id:
            self._exchange_to_local[str(result.order_id)] = local.order_id

        status = result.status.upper()
        if status in {"REJECTED", "EXPIRED", "CANCELED", "CANCELLED", "EXPIRED_IN_MATCH"}:
            self.manager.reject(local.order_id, reason=result.message)
        # The REST acknowledgement is not the authoritative fill record. The
        # private ORDER_TRADE_UPDATE stream carries executed quantity/trade id/
        # average price/commission and therefore controls local fill state.
        return result

    def bind_exchange_order(self, exchange_order_id: str, local_order_id: str) -> None:
        """Restore the exchange-to-local binding after restart/reconciliation."""
        if self.manager.get(local_order_id) is None:
            raise ValueError(f"unknown_local_order:{local_order_id}")
        self._exchange_to_local[str(exchange_order_id)] = str(local_order_id)

    def local_order_id(self, exchange_order_id: str) -> str | None:
        return self._exchange_to_local.get(str(exchange_order_id))

    def cancel(self, order_id: str) -> ExecutionResult:
        local_id = self._exchange_to_local.get(str(order_id), str(order_id))
        order = self.manager.get(local_id)
        if order is None:
            return ExecutionResult("REJECTED_UNKNOWN_ORDER", None, "unknown order")
        try:
            result = self.adapter.cancel(str(order_id), order.symbol)
        except Exception as exc:
            self.risk_gate.emergency_stop()
            return ExecutionResult("CANCEL_UNKNOWN", str(order_id),
                                   f"cancel outcome unknown: {type(exc).__name__}")
        status = result.status.upper()
        if status in {"CANCELED", "CANCELLED", "EXPIRED", "EXPIRED_IN_MATCH"}:
            self.manager.cancel(local_id)
        return result
