"""V12 exit engine — deterministic exit rules.

No discretionary exits. Exit decisions account for:
- signal reversal
- expected-edge decay
- target
- stop
- maximum holding time
- adverse selection
- risk limits
- emergency conditions

Every exit reason must be logged.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ExitReason(Enum):
    SIGNAL_REVERSAL = "SIGNAL_REVERSAL"
    EDGE_DECAY = "EDGE_DECAY"
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"
    MAX_HOLD_TIME = "MAX_HOLD_TIME"
    ADVERSE_SELECTION = "ADVERSE_SELECTION"
    RISK_LIMIT = "RISK_LIMIT"
    EMERGENCY = "EMERGENCY"
    FUNDING_EXPIRED = "FUNDING_EXPIRED"
    SPREAD_WIDENED = "SPREAD_WIDENED"
    LIQUIDITY_DRIED = "LIQUIDITY_DRIED"


@dataclass(frozen=True)
class V12ExitConfig:
    """Frozen exit configuration."""
    max_hold_hours: float = 16.0
    stop_loss_bps: float = 50.0
    take_profit_bps: float = 50.0
    min_edge_bps: float = 1.0  # minimum edge to hold
    adverse_selection_threshold_bps: float = 10.0
    spread_widen_threshold_bps: float = 5.0
    liquidity_min_depth_usd: float = 10000.0


@dataclass
class V12ExitDecision:
    """Exit decision result."""
    should_exit: bool
    reason: ExitReason
    urgency: str  # NORMAL, URGENT, EMERGENCY
    details: str = ""


class V12ExitEngine:
    """Deterministic exit engine."""

    def __init__(self, config: V12ExitConfig | None = None):
        self._config = config or V12ExitConfig()

    def evaluate(
        self,
        position_side: str,
        entry_price: float,
        mark_price: float,
        entry_ts_ms: int,
        max_hold_ts_ms: int,
        stop_loss_price: float,
        take_profit_price: float,
        current_edge_bps: float,
        adverse_selection_bps: float,
        spread_bps: float,
        depth_usd: float,
        funding_rate: float,
        ts_ms: int,
    ) -> V12ExitDecision:
        """Evaluate exit conditions in priority order."""

        # 1. Emergency check (should come from risk engine)
        # Not handled here - risk engine halts trading

        # 2. Max hold time
        if ts_ms >= max_hold_ts_ms:
            return V12ExitDecision(True, ExitReason.MAX_HOLD_TIME, "EMERGENCY", f"Max hold time reached at {ts_ms}")

        # 3. Stop loss
        if position_side == "LONG" and mark_price <= stop_loss_price:
            return V12ExitDecision(True, ExitReason.STOP_LOSS, "EMERGENCY", f"Stop loss hit: {mark_price} <= {stop_loss_price}")
        if position_side == "SHORT" and mark_price >= stop_loss_price:
            return V12ExitDecision(True, ExitReason.STOP_LOSS, "EMERGENCY", f"Stop loss hit: {mark_price} >= {stop_loss_price}")

        # 4. Take profit
        if position_side == "LONG" and mark_price >= take_profit_price:
            return V12ExitDecision(True, ExitReason.TAKE_PROFIT, "NORMAL", f"Take profit hit: {mark_price} >= {take_profit_price}")
        if position_side == "SHORT" and mark_price <= take_profit_price:
            return V12ExitDecision(True, ExitReason.TAKE_PROFIT, "NORMAL", f"Take profit hit: {mark_price} <= {take_profit_price}")

        # 5. Risk limits (adverse selection)
        if adverse_selection_bps >= self._config.adverse_selection_threshold_bps:
            return V12ExitDecision(True, ExitReason.ADVERSE_SELECTION, "URGENT", f"Adverse selection: {adverse_selection_bps} bps")

        # 6. Spread widened
        if spread_bps >= self._config.spread_widen_threshold_bps:
            return V12ExitDecision(True, ExitReason.SPREAD_WIDENED, "URGENT", f"Spread widened: {spread_bps} bps")

        # 7. Liquidity dried
        # if depth_usd < self._config.liquidity_min_depth_usd:
        #     return V12ExitDecision(True, ExitReason.LIQUIDITY_DRIED, "URGENT", f"Liquidity dried: {depth_usd} USD")

        # 8. Edge decay (signal no longer strong enough)
        if current_edge_bps < self._config.min_edge_bps:
            return V12ExitDecision(True, ExitReason.EDGE_DECAY, "NORMAL", f"Edge decayed: {current_edge_bps} < {self._config.min_edge_bps}")

        # 9. Signal reversal (would come from signal model)
        # Not evaluated here - external signal check

        return V12ExitDecision(False, ExitReason.SIGNAL_REVERSAL, "NORMAL", "No exit condition met")

    def log_exit(self, reason: ExitReason, details: str, position_state: dict):
        """Log exit for audit trail."""
        # In production, this would write to audit log
        pass