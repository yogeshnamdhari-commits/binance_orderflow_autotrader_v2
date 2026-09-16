from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence
import numpy as np

from app.v19.features import L2Event


@dataclass(frozen=True)
class InventoryState:
    position: float
    position_notional_usd: float
    unrealized_pnl_bps: float
    inventory_ratio: float
    max_position_notional_usd: float
    risk_status: str


class InventoryManager:
    def __init__(
        self,
        inventory_target: float = 0.0,
        inventory_penalty_bps: float = 0.50,
        max_position_notional_usd: float = 5000.0,
    ):
        self.inventory_target = inventory_target
        self.inventory_penalty_bps = inventory_penalty_bps
        self.max_position_notional_usd = max_position_notional_usd

    def update(
        self,
        position: float,
        current_price: float,
        side: str,
        qty: float,
    ) -> InventoryState:
        if side == "BUY":
            new_position = position + qty
        elif side == "SELL":
            new_position = position - qty
        else:
            new_position = position

        position_notional = abs(new_position) * current_price
        inventory_ratio = new_position / (self.max_position_notional_usd / current_price) if current_price > 0 else 0.0
        unrealized_pnl = self._compute_unrealized_pnl(new_position, current_price)

        risk_status = self._assess_risk(inventory_ratio, position_notional)

        return InventoryState(
            position=float(new_position),
            position_notional_usd=float(position_notional),
            unrealized_pnl_bps=float(unrealized_pnl),
            inventory_ratio=float(inventory_ratio),
            max_position_notional_usd=self.max_position_notional_usd,
            risk_status=risk_status,
        )

    def _compute_unrealized_pnl(self, position: float, current_price: float) -> float:
        if current_price <= 0:
            return 0.0
        return float(position * current_price * 10_000.0 / current_price)

    def _assess_risk(self, inventory_ratio: float, position_notional: float) -> str:
        if abs(inventory_ratio) > 0.8:
            return "CRITICAL"
        elif abs(inventory_ratio) > 0.5:
            return "HIGH"
        elif abs(inventory_ratio) > 0.3:
            return "MODERATE"
        elif position_notional > self.max_position_notional_usd * 0.8:
            return "ELEVATED"
        else:
            return "NORMAL"

    def skew_quotes(
        self,
        quote_state: dict,
        current_price: float,
    ) -> dict:
        inventory_ratio = quote_state.get("inventory", 0.0) / (
            self.max_position_notional_usd / current_price if current_price > 0 else 1.0
        )
        skew_bps = self.inventory_penalty_bps * np.clip(inventory_ratio, -1.0, 1.0)
        return {"skew_bps": float(skew_bps), "inventory_ratio": float(inventory_ratio)}
