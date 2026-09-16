from __future__ import annotations

from dataclasses import dataclass

from .execution_gateway import ExecutionGateway, Submission
from .live_market_data import MarketDataGuard
from .live_pnl import Fill, LivePnL, PnLSnapshot
from .live_risk import LiveRiskGate
from .reconciliation import (
    ExchangeOrder,
    LocalOrder,
    PositionState,
    ReconciliationResult,
    reconcile,
)
from .user_stream import UserStreamGuard


@dataclass(frozen=True)
class RuntimeStatus:
    can_quote: bool
    can_submit: bool
    reasons: tuple[str, ...]
    reconciliation: ReconciliationResult | None


class V20LiveRuntime:
    """Coordinates V20 live health, risk, reconciliation and execution.

    The strategy supplies quote intentions; this runtime decides whether they
    may cross the execution boundary. It never overrides a failed safety gate.
    Exchange fills update the authoritative idempotent P&L state.
    """

    def __init__(self, gateway: ExecutionGateway, risk: LiveRiskGate | None = None):
        self.gateway = gateway
        self.risk = risk or gateway.risk_gate
        self.market = MarketDataGuard(self.risk.limits.max_market_data_age_ms)
        self.user = UserStreamGuard(self.risk.limits.max_user_stream_age_ms)
        self.pnl = LivePnL()
        self.last_reconciliation: ReconciliationResult | None = None
        self.last_pnl: PnLSnapshot | None = None

    def set_reconciliation(
        self,
        local_orders: dict[str, LocalOrder],
        exchange_orders: dict[str, ExchangeOrder],
        local_position: PositionState,
        exchange_position: PositionState,
    ) -> ReconciliationResult:
        result = reconcile(local_orders, exchange_orders, local_position, exchange_position)
        self.last_reconciliation = result
        self.risk.update_reconciliation(result.ok)
        return result

    def apply_exchange_fill(self, fill: Fill, mark_price: float) -> PnLSnapshot:
        self.pnl.apply_fill(fill)
        snap = self.pnl.snapshot(mark_price)
        self.last_pnl = snap
        self.risk.update_position(abs(snap.position_qty), abs(snap.position_qty) * mark_price)
        self.risk.update_pnl(snap.net_pnl_usd)
        return snap

    def mark_to_market(self, mark_price: float) -> PnLSnapshot:
        snap = self.pnl.snapshot(mark_price)
        self.last_pnl = snap
        self.risk.update_position(abs(snap.position_qty), abs(snap.position_qty) * mark_price)
        self.risk.update_pnl(snap.net_pnl_usd)
        return snap

    def heartbeat(self, now_ms: int) -> RuntimeStatus:
        market = self.market.health(now_ms)
        user_ok, user_age, _ = self.user.health(now_ms)
        self.risk.update_market_health(market.age_ms, market.ready)
        self.risk.update_user_stream_health(user_age, user_ok)
        can_quote, reasons = self.risk.can_quote()
        can_submit, submit_reasons = self.risk.can_submit(0.0)
        all_reasons = tuple(dict.fromkeys([*reasons, *submit_reasons]))
        return RuntimeStatus(can_quote, can_submit and can_quote, all_reasons, self.last_reconciliation)

    def submit(self, submission: Submission, now_ms: int):
        status = self.heartbeat(now_ms)
        if not status.can_quote:
            return self.gateway.submit(submission)
        return self.gateway.submit(submission)

    def emergency_stop(self) -> list[str]:
        self.risk.emergency_stop()
        return self.gateway.manager.emergency_close_all(reason="runtime_emergency_stop")
