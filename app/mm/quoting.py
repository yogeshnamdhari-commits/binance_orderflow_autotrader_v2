from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence
import numpy as np

from app.v19.features import L2Event, compute_orderflow_features


@dataclass(frozen=True)
class Quote:
    side: str
    price: float
    qty: float
    timestamp_ns: int
    cancel_reason: str = ""


@dataclass(frozen=True)
class QuoteState:
    bid_price: float
    bid_qty: float
    ask_price: float
    ask_qty: float
    inventory: float
    reservation_price: float
    half_spread_bps: float
    volatility_regime: int


class QuoteEngine:
    def __init__(
        self,
        base_half_spread_bps: float = 0.75,
        max_half_spread_bps: float = 2.50,
        inventory_penalty_bps: float = 0.50,
        inventory_target: float = 0.0,
        adverse_selection_threshold_bps: float = 0.75,
        cancel_on_adverse_selection: bool = True,
    ):
        self.base_half_spread_bps = base_half_spread_bps
        self.max_half_spread_bps = max_half_spread_bps
        self.inventory_penalty_bps = inventory_penalty_bps
        self.inventory_target = inventory_target
        self.adverse_selection_threshold_bps = adverse_selection_threshold_bps
        self.cancel_on_adverse_selection = cancel_on_adverse_selection

    def compute_reservation_price(
        self,
        mid: float,
        alpha_skew_bps: float,
        inventory: float,
        max_position_notional_usd: float,
        current_price: float,
    ) -> float:
        inventory_penalty = self._inventory_skew_bps(
            inventory, max_position_notional_usd, current_price
        )
        reservation_price = mid * (1.0 + (alpha_skew_bps - inventory_penalty) / 10_000.0)
        return float(reservation_price)

    def _inventory_skew_bps(
        self,
        inventory: float,
        max_position_notional_usd: float,
        current_price: float,
    ) -> float:
        if max_position_notional_usd <= 0 or current_price <= 0:
            return 0.0
        max_qty = max_position_notional_usd / current_price
        if max_qty <= 0:
            return 0.0
        inventory_ratio = inventory / max_qty
        return float(self.inventory_penalty_bps * np.clip(inventory_ratio, -1.0, 1.0))

    def compute_half_spread(
        self,
        spread_bps: float,
        volatility_regime: int,
        depth_concentration: float,
    ) -> float:
        regime_multiplier = {0: 0.8, 1: 1.0, 2: 1.3}[volatility_regime]
        depth_multiplier = 1.0 + (1.0 - depth_concentration) * 0.5
        half_spread = self.base_half_spread_bps * regime_multiplier * depth_multiplier
        return float(min(half_spread, self.max_half_spread_bps))

    def generate_quotes(
        self,
        events: Sequence[L2Event],
        now_ns: int,
        current_price: float,
        inventory: float,
        max_position_notional_usd: float,
    ) -> QuoteState:
        features = compute_orderflow_features(events, now_ns)
        mid = current_price
        spread_bps = features["spread_bps"]
        depth_concentration = features["depth_concentration"]
        volatility_regime = int(features["volatility_regime"])

        alpha_skew_bps = self._compute_alpha_skew(features)
        reservation_price = self.compute_reservation_price(
            mid, alpha_skew_bps, inventory, max_position_notional_usd, current_price
        )
        half_spread = self.compute_half_spread(
            spread_bps, volatility_regime, depth_concentration
        )

        bid_price = reservation_price * (1.0 - half_spread / 10_000.0)
        ask_price = reservation_price * (1.0 + half_spread / 10_000.0)

        bid_qty = self._compute_qty(features, side="bid", inventory=inventory)
        ask_qty = self._compute_qty(features, side="ask", inventory=inventory)

        return QuoteState(
            bid_price=float(bid_price),
            bid_qty=float(bid_qty),
            ask_price=float(ask_price),
            ask_qty=float(ask_qty),
            inventory=inventory,
            reservation_price=float(reservation_price),
            half_spread_bps=half_spread,
            volatility_regime=volatility_regime,
        )

    def _compute_alpha_skew(self, features: dict) -> float:
        ofi_1 = features["ofi_1_zscore"]
        ofi_3 = features["ofi_3_zscore"]
        signed_flow = features["signed_trade_flow_zscore"]
        alpha_skew = (ofi_1 * 0.3 + ofi_3 * 0.4 + signed_flow * 0.3) * 0.5
        return float(np.clip(alpha_skew, -2.0, 2.0))

    def _compute_qty(
        self, features: dict, side: str, inventory: float
    ) -> float:
        depth_concentration = features["depth_concentration"]
        base_qty = 0.001 * depth_concentration
        inventory_skew = 1.0 - abs(inventory) * 0.5
        return float(max(base_qty * inventory_skew, 0.0001))

    def should_cancel(
        self,
        quote_state: QuoteState,
        features: dict,
        adverse_selection_bps: float,
    ) -> tuple[bool, str]:
        if not self.cancel_on_adverse_selection:
            return False, ""
        if adverse_selection_bps > self.adverse_selection_threshold_bps:
            return True, f"adverse_selection_{adverse_selection_bps:.4f}_bps"
        if abs(quote_state.inventory) > 0.5:
            return True, f"inventory_risk_{quote_state.inventory:.2f}"
        return False, ""
