from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class RiskLimits:
    max_position_units: float = 0.05
    max_position_notional_usd: float = 5000.0
    max_order_qty: float = 0.01
    max_open_orders: int = 4
    max_market_data_age_ms: int = 1000
    max_user_stream_age_ms: int = 5000
    max_daily_loss_usd: float = 50.0
    max_api_errors: int = 5
    max_quote_age_ms: int = 1000


@dataclass
class RiskState:
    position_units: float = 0.0
    mark_price: float = 0.0
    open_orders: int = 0
    daily_realized_pnl_usd: float = 0.0
    api_errors: int = 0
    market_data_age_ms: int = 10**9
    user_stream_age_ms: int = 10**9
    quote_age_ms: int = 10**9
    reconciled: bool = False
    market_ready: bool = False
    user_stream_ready: bool = False
    emergency_latched: bool = False
    session_day: Optional[date] = None


class LiveRiskGate:
    """Fail-closed production risk gate.

    The gate permits quoting/submission only when every required dependency is
    healthy. Any missing or stale state returns NO_TRADE.
    """

    def __init__(self, limits: RiskLimits | None = None):
        self.limits = limits or RiskLimits()
        self.state = RiskState()

    def latch(self, reason: str) -> None:
        self.state.emergency_latched = True

    def emergency_stop(self) -> None:
        """Latch the system into NO-TRADE until reconciliation clears it."""
        self.latch("emergency stop")

    def reset_after_reconciliation(self) -> None:
        if self.state.reconciled and self.state.market_ready and self.state.user_stream_ready:
            self.state.emergency_latched = False

    def update_position(self, position_units: float, mark_price: float) -> None:
        self.state.position_units = float(position_units)
        self.state.mark_price = float(mark_price)

    def update_market_health(self, age_ms: int, ready: bool) -> None:
        self.state.market_data_age_ms = int(age_ms)
        self.state.market_ready = bool(ready)

    def update_user_stream_health(self, age_ms: int, ready: bool) -> None:
        self.state.user_stream_age_ms = int(age_ms)
        self.state.user_stream_ready = bool(ready)

    def update_quote_age(self, age_ms: int) -> None:
        self.state.quote_age_ms = int(age_ms)

    def update_orders(self, open_orders: int) -> None:
        self.state.open_orders = int(open_orders)

    def update_pnl(self, daily_realized_pnl_usd: float) -> None:
        self.state.daily_realized_pnl_usd = float(daily_realized_pnl_usd)

    def update_api_errors(self, api_errors: int) -> None:
        self.state.api_errors = int(api_errors)

    def update_reconciliation(self, reconciled: bool) -> None:
        self.state.reconciled = bool(reconciled)
        if not reconciled:
            self.latch("reconciliation mismatch")

    def _common(self) -> list[str]:
        s = self.state
        l = self.limits
        reasons: list[str] = []
        if s.emergency_latched:
            reasons.append("emergency_latched")
        if not s.market_ready or s.market_data_age_ms > l.max_market_data_age_ms:
            reasons.append("market_data_unhealthy")
        if not s.user_stream_ready or s.user_stream_age_ms > l.max_user_stream_age_ms:
            reasons.append("user_stream_unhealthy")
        if not s.reconciled:
            reasons.append("state_not_reconciled")
        if abs(s.position_units) > l.max_position_units:
            reasons.append("position_limit")
        if s.mark_price > 0 and abs(s.position_units * s.mark_price) > l.max_position_notional_usd:
            reasons.append("notional_limit")
        if s.open_orders >= l.max_open_orders:
            reasons.append("open_order_limit")
        if s.daily_realized_pnl_usd <= -abs(l.max_daily_loss_usd):
            reasons.append("daily_loss_limit")
        if s.api_errors >= l.max_api_errors:
            reasons.append("api_error_limit")
        if s.quote_age_ms > l.max_quote_age_ms:
            reasons.append("quote_stale")
        return reasons

    def can_quote(self) -> tuple[bool, tuple[str, ...]]:
        reasons = self._common()
        return (len(reasons) == 0, tuple(reasons))

    def can_submit(self, qty: float) -> tuple[bool, tuple[str, ...]]:
        reasons = self._common()
        if qty <= 0:
            reasons.append("invalid_quantity")
        if qty > self.limits.max_order_qty:
            reasons.append("order_size_limit")
        return (len(reasons) == 0, tuple(reasons))
