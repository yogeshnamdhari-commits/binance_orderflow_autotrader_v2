"""V12 position engine — local position tracking with exchange reconciliation.

The local position must continuously reconcile against Binance exchange state.
If LOCAL POSITION != EXCHANGE POSITION -> HALT NEW TRADES + RECONCILE + ALERT
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .config import V12Config


class PositionSide(Enum):
    FLAT = "FLAT"
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class V12Position:
    """Single position state."""
    side: PositionSide = PositionSide.FLAT
    qty_btc: float = 0.0
    entry_price: float = 0.0
    entry_ts_ms: int = 0
    entry_funding_rate: float = 0.0
    unrealized_pnl_bps: float = 0.0
    realized_pnl_bps: float = 0.0
    funding_accrued_bps: float = 0.0
    stop_loss_price: float = 0.0
    take_profit_price: float = 0.0
    max_hold_ts_ms: int = 0


class V12PositionEngine:
    """Manages local position with exchange reconciliation."""

    def __init__(self, config: V12Config | None = None):
        self._cfg = config or V12Config()
        self._position = V12Position()
        self._last_reconcile_ts = 0
        self._reconcile_interval_ms = 30000  # 30 seconds

    @property
    def position(self) -> V12Position:
        return self._position

    def is_flat(self) -> bool:
        return self._position.side == PositionSide.FLAT

    def on_entry(self, side: str, qty_btc: float, price: float, ts_ms: int, funding_rate: float, stop_loss: float, take_profit: float, max_hold_hours: float):
        """Record new position entry."""
        self._position.side = PositionSide.LONG if side == "BUY" else PositionSide.SHORT
        self._position.qty_btc = qty_btc
        self._position.entry_price = price
        self._position.entry_ts_ms = ts_ms
        self._position.entry_funding_rate = funding_rate
        self._position.stop_loss_price = stop_loss
        self._position.take_profit_price = take_profit
        self._position.max_hold_ts_ms = ts_ms + int(max_hold_hours * 3600 * 1000)

    def on_exit(self, exit_price: float, exit_ts_ms: int) -> float:
        """Record position exit and return realized P&L in bps."""
        if self._position.side == PositionSide.FLAT:
            return 0.0

        if self._position.side == PositionSide.LONG:
            pnl_bps = (exit_price - self._position.entry_price) / self._position.entry_price * 1e4
        else:
            pnl_bps = (self._position.entry_price - exit_price) / self._position.entry_price * 1e4

        self._position.realized_pnl_bps += pnl_bps
        self._position.side = PositionSide.FLAT
        self._position.qty_btc = 0.0
        self._position.entry_price = 0.0
        self._position.entry_ts_ms = 0
        self._position.stop_loss_price = 0.0
        self._position.take_profit_price = 0.0
        self._position.max_hold_ts_ms = 0
        return pnl_bps

    def update_unrealized(self, mark_price: float, funding_rate: float):
        """Update unrealized P&L and funding accrual."""
        if self._position.side == PositionSide.FLAT:
            return

        if self._position.side == PositionSide.LONG:
            self._position.unrealized_pnl_bps = (mark_price - self._position.entry_price) / self._position.entry_price * 1e4
            # Funding income for longs (if funding > 0)
            self._position.funding_accrued_bps += funding_rate * 1e4 * (8.0 / 24.0)  # per 8h period
        else:
            self._position.unrealized_pnl_bps = (self._position.entry_price - mark_price) / self._position.entry_price * 1e4
            # Funding cost for shorts (if funding > 0)
            self._position.funding_accrued_bps -= funding_rate * 1e4 * (8.0 / 24.0)

    def check_exit_conditions(self, mark_price: float, ts_ms: int) -> tuple[bool, str]:
        """Check if position should be exited. Returns (should_exit, reason)."""
        if self._position.side == PositionSide.FLAT:
            return False, "FLAT"

        # Time-based exit
        if ts_ms >= self._position.max_hold_ts_ms:
            return True, "MAX_HOLD_TIME"

        # Stop loss
        if self._position.side == PositionSide.LONG and mark_price <= self._position.stop_loss_price:
            return True, "STOP_LOSS"
        if self._position.side == PositionSide.SHORT and mark_price >= self._position.stop_loss_price:
            return True, "STOP_LOSS"

        # Take profit
        if self._position.side == PositionSide.LONG and mark_price >= self._position.take_profit_price:
            return True, "TAKE_PROFIT"
        if self._position.side == PositionSide.SHORT and mark_price <= self._position.take_profit_price:
            return True, "TAKE_PROFIT"

        return False, "HOLD"

    def reconcile(self, exchange_pos_btc: float, exchange_side: str) -> tuple[bool, str]:
        """Reconcile local position with exchange state."""
        local_qty = self._position.qty_btc
        local_side = self._position.side.value

        # Convert exchange side to enum
        if exchange_side.upper() in ("LONG", "BUY"):
            exch_side = PositionSide.LONG
        elif exchange_side.upper() in ("SHORT", "SELL"):
            exch_side = PositionSide.SHORT
        else:
            exch_side = PositionSide.FLAT

        # Check for mismatch
        if abs(local_qty - exchange_pos_btc) > 1e-8:
            return False, f"QTY_MISMATCH: local={local_qty}, exchange={exchange_pos_btc}"

        if local_side != exch_side.value:
            return False, f"SIDE_MISMATCH: local={local_side}, exchange={exch_side.value}"

        return True, "OK"

    def get_state(self) -> dict:
        return {
            "side": self._position.side.value,
            "qty_btc": self._position.qty_btc,
            "entry_price": self._position.entry_price,
            "unrealized_pnl_bps": self._position.unrealized_pnl_bps,
            "realized_pnl_bps": self._position.realized_pnl_bps,
            "funding_accrued_bps": self._position.funding_accrued_bps,
            "max_hold_remaining_hours": max(0, (self._position.max_hold_ts_ms - int(datetime.now(timezone.utc).timestamp() * 1000)) / 3600000),
        }