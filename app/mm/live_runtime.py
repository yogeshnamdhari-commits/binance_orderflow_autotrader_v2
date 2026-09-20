from __future__ import annotations

from dataclasses import dataclass

from .execution_gateway import ExecutionGateway, Submission
from .live_market_data import MarketDataGuard
from .live_pnl import Fill, LivePnL, PnLSnapshot
from .live_risk import LiveRiskGate
from .reconciliation import ExchangeOrder, LocalOrder, PositionState, ReconciliationResult, reconcile
from .user_stream import OrderUpdate, PositionUpdate, UserStreamGuard


@dataclass(frozen=True)
class RuntimeStatus:
    can_quote: bool
    can_submit: bool
    reasons: tuple[str, ...]
    reconciliation: ReconciliationResult | None


class V20LiveRuntime:
    """Coordinates V20 live health, risk, reconciliation and execution."""

    def __init__(self, gateway: ExecutionGateway, risk: LiveRiskGate | None = None):
        self.gateway = gateway
        self.risk = risk or gateway.risk_gate
        self.market = MarketDataGuard(self.risk.limits.max_market_data_age_ms)
        self.user = UserStreamGuard(self.risk.limits.max_user_stream_age_ms)
        self.pnl = LivePnL()
        self.last_reconciliation: ReconciliationResult | None = None
        self.last_pnl: PnLSnapshot | None = None

    def set_reconciliation(self, local_orders: dict[str, LocalOrder], exchange_orders: dict[str, ExchangeOrder],
                           local_position: PositionState, exchange_position: PositionState) -> ReconciliationResult:
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

    def apply_order_update(self, update: OrderUpdate, mark_price: float) -> PnLSnapshot | None:
        local_id = self.gateway.local_order_id(update.order_id)
        if local_id is None and update.client_id:
            local = self.gateway.manager.get_by_client_id(update.client_id)
            local_id = local.order_id if local else None
            if local_id is not None and update.order_id:
                self.gateway.bind_exchange_order(update.order_id, local_id)

        order = self.gateway.manager.get(local_id) if local_id else None
        if order is not None:
            if update.status == "REJECTED":
                self.gateway.manager.reject(order.order_id, reason="exchange_rejected")
            elif update.status in {"CANCELED", "CANCELLED", "EXPIRED", "EXPIRED_IN_MATCH"}:
                self.gateway.manager.cancel(order.order_id)
            elif update.execution_type == "TRADE" and update.last_fill_qty > 0 and update.last_fill_price > 0:
                self.gateway.manager.mark_filled(order.order_id, update.last_fill_price, update.last_fill_qty)

        if update.execution_type == "TRADE" and update.last_fill_qty > 0 and update.last_fill_price > 0:
            self.apply_exchange_fill(
                Fill(
                    trade_id=update.trade_id or f"{update.order_id}:{update.event_ts_ms}:{update.last_fill_qty}",
                    side=update.side,
                    qty=update.last_fill_qty,
                    price=update.last_fill_price,
                    fee_usd=update.commission if update.commission_asset in {"USDT", "USD", ""} else 0.0,
                ),
                mark_price,
            )
        return self.last_pnl

    def apply_position_update(self, update: PositionUpdate, mark_price: float) -> PnLSnapshot:
        snap = self.pnl.snapshot(mark_price)
        self.last_pnl = snap
        self.risk.update_position(abs(update.quantity), abs(update.quantity) * mark_price)
        self.risk.update_pnl(snap.net_pnl_usd)
        return snap

    def handle_user_stream_failure(self, event_type: str) -> None:
        if event_type in {"listenKeyExpired", "MARGIN_CALL", "USER_STREAM_ERROR", "USER_STREAM_KEEPALIVE_FAILED"}:
            self.risk.emergency_stop()

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
        return RuntimeStatus(can_quote, can_quote and self.gateway.live_enabled, tuple(reasons), self.last_reconciliation)

    def submit(self, submission: Submission, now_ms: int):
        self.heartbeat(now_ms)
        return self.gateway.submit(submission)

    def emergency_stop(self) -> list[str]:
        self.risk.emergency_stop()
        return self.gateway.manager.emergency_close_all(reason="runtime_emergency_stop")
