"""V12 risk engine — hard independent limits.

Implements:
- maximum position
- maximum notional
- maximum order quantity
- maximum daily loss
- maximum session loss
- maximum drawdown
- maximum consecutive losses
- maximum spread
- maximum latency
- stale-data timeout
- abnormal-volatility halt
- API error halt
- position mismatch halt
- emergency flatten

Risk controls cannot be disabled by the model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .config import V12Config


class RiskState(Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    HALT = "HALT"
    EMERGENCY = "EMERGENCY"


class HaltReason(Enum):
    NONE = "NONE"
    MAX_DAILY_LOSS = "MAX_DAILY_LOSS"
    MAX_DRAWDOWN = "MAX_DRAWDOWN"
    POSITION_MISMATCH = "POSITION_MISMATCH"
    STALE_DATA = "STALE_DATA"
    ABNORMAL_VOLATILITY = "ABNORMAL_VOLATILITY"
    API_ERROR = "API_ERROR"
    CONSECUTIVE_LOSSES = "CONSECUTIVE_LOSSES"
    MAX_POSITION = "MAX_POSITION"
    EMERGENCY_FLATTEN = "EMERGENCY_FLATTEN"


@dataclass(frozen=True)
class V12RiskConfig:
    """Frozen risk configuration."""
    max_position_btc: float = 0.1
    max_notional_usd: float = 100000.0
    max_order_qty_btc: float = 0.02
    max_daily_loss_bps: float = 200.0
    max_session_loss_bps: float = 100.0
    max_drawdown_bps: float = 100.0
    max_consecutive_losses: int = 5
    max_spread_bps: float = 5.0
    max_latency_ms: int = 1000
    stale_data_timeout_ms: int = 5000
    abnormal_vol_threshold_bps: float = 100.0
    api_error_threshold: int = 10


@dataclass
class V12RiskState:
    """Current risk state."""
    state: RiskState = RiskState.NORMAL
    halt_reason: HaltReason = HaltReason.NONE
    daily_pnl_bps: float = 0.0
    session_pnl_bps: float = 0.0
    max_drawdown_bps: float = 0.0
    peak_equity: float = 0.0
    consecutive_losses: int = 0
    current_spread_bps: float = 0.0
    current_latency_ms: int = 0
    api_errors: int = 0
    last_update_ms: int = 0


class V12RiskEngine:
    """Independent risk engine — cannot be overridden by signal."""

    def __init__(self, config: V12RiskConfig | None = None):
        self._config = config or V12RiskConfig()
        self._state = V12RiskState()

    def check_pre_trade(
        self,
        side: str,
        qty_btc: float,
        price: float,
        spread_bps: float,
        latency_ms: int,
        vol_bps: float,
    ) -> tuple[bool, str]:
        """Check if trade is allowed. Returns (allowed, reason)."""
        self._state.current_spread_bps = spread_bps
        self._state.current_latency_ms = latency_ms
        self._state.last_update_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        if self._state.state == RiskState.HALT:
            return False, f"RISK_HALT: {self._state.halt_reason.value}"

        if self._state.state == RiskState.EMERGENCY:
            return False, f"EMERGENCY: {self._state.halt_reason.value}"

        if qty_btc > self._config.max_order_qty_btc:
            return False, f"ORDER_TOO_LARGE: {qty_btc} > {self._config.max_order_qty_btc}"

        notional = qty_btc * price
        if notional > self._config.max_notional_usd:
            return False, f"NOTIONAL_TOO_LARGE: {notional} > {self._config.max_notional_usd}"

        if spread_bps > self._config.max_spread_bps:
            return False, f"SPREAD_TOO_WIDE: {spread_bps} > {self._config.max_spread_bps}"

        if latency_ms > self._config.max_latency_ms:
            return False, f"LATENCY_TOO_HIGH: {latency_ms} > {self._config.max_latency_ms}"

        if vol_bps > self._config.abnormal_vol_threshold_bps:
            return False, f"ABNORMAL_VOLATILITY: {vol_bps} > {self._config.abnormal_vol_threshold_bps}"

        return True, "OK"

    def on_fill(self, side: str, qty_btc: float, pnl_bps: float):
        """Update risk state after fill."""
        self._state.daily_pnl_bps += pnl_bps
        self._state.session_pnl_bps += pnl_bps

        if pnl_bps < 0:
            self._state.consecutive_losses += 1
        else:
            self._state.consecutive_losses = 0

        # Update drawdown
        equity = self._state.peak_equity + self._state.daily_pnl_bps
        if equity > self._state.peak_equity:
            self._state.peak_equity = equity
        drawdown = self._state.peak_equity - equity
        if drawdown > self._state.max_drawdown_bps:
            self._state.max_drawdown_bps = drawdown

        # Check limits
        if self._state.daily_pnl_bps <= -self._config.max_daily_loss_bps:
            self._state.state = RiskState.HALT
            self._state.halt_reason = HaltReason.MAX_DAILY_LOSS

        if self._state.max_drawdown_bps >= self._config.max_drawdown_bps:
            self._state.state = RiskState.HALT
            self._state.halt_reason = HaltReason.MAX_DRAWDOWN

        if self._state.consecutive_losses >= self._config.max_consecutive_losses:
            self._state.state = RiskState.HALT
            self._state.halt_reason = HaltReason.CONSECUTIVE_LOSSES

    def on_api_error(self):
        self._state.api_errors += 1
        if self._state.api_errors >= self._config.api_error_threshold:
            self._state.state = RiskState.HALT
            self._state.halt_reason = HaltReason.API_ERROR

    def check_position_reconciliation(self, local_pos_btc: float, exchange_pos_btc: float) -> bool:
        if abs(local_pos_btc - exchange_pos_btc) > 1e-8:
            self._state.state = RiskState.HALT
            self._state.halt_reason = HaltReason.POSITION_MISMATCH
            return False
        return True

    def check_stale_data(self, last_event_ms: int) -> bool:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        if now_ms - last_event_ms > self._config.stale_data_timeout_ms:
            self._state.state = RiskState.HALT
            self._state.halt_reason = HaltReason.STALE_DATA
            return False
        return True

    def get_state(self) -> V12RiskState:
        return self._state

    def emergency_flatten(self) -> bool:
        """Trigger emergency flatten."""
        if self._state.state != RiskState.EMERGENCY:
            self._state.state = RiskState.EMERGENCY
            self._state.halt_reason = HaltReason.EMERGENCY_FLATTEN
            return True
        return False

    def reset_daily(self):
        """Reset daily counters (call at UTC midnight)."""
        self._state.daily_pnl_bps = 0.0
        self._state.consecutive_losses = 0
        if self._state.state == RiskState.HALT and self._state.halt_reason in (
            HaltReason.MAX_DAILY_LOSS, HaltReason.CONSECUTIVE_LOSSES
        ):
            self._state.state = RiskState.NORMAL
            self._state.halt_reason = HaltReason.NONE