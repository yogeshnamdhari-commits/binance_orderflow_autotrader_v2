"""V21 order-flow decision layer.

This layer combines a probabilistic directional estimate and side-specific
toxicity estimates with inventory-aware passive quoting. It is research-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.research.v21_orderflow_core import AlphaEstimate, BookTop


@dataclass(frozen=True)
class ToxicityEstimate:
    probability: float
    expected_adverse_bps: float

    @property
    def expected_cost_bps(self) -> float:
        return max(0.0, self.probability) * max(0.0, self.expected_adverse_bps)


@dataclass(frozen=True)
class V21Decision:
    bid_price: Optional[float]
    ask_price: Optional[float]
    bid_enabled: bool
    ask_enabled: bool
    bid_edge_bps: float
    ask_edge_bps: float
    bid_toxicity_cost_bps: float
    ask_toxicity_cost_bps: float
    bid_crossing_request: bool
    ask_crossing_request: bool
    reservation_shift_bps: float
    reason: str


class V21DecisionEngine:
    """Strict passive quote decision engine.

    The engine never converts a crossing quote into a passive quote. A crossing
    request disables that side and is returned in the decision trace.
    """

    def __init__(
        self,
        *,
        tick_size: float,
        maker_fee_bps: float,
        min_edge_bps: float,
        inventory_penalty_bps: float,
    ) -> None:
        if tick_size <= 0:
            raise ValueError("tick_size must be positive")
        self.tick_size = tick_size
        self.maker_fee_bps = maker_fee_bps
        self.min_edge_bps = min_edge_bps
        self.inventory_penalty_bps = inventory_penalty_bps

    def _floor(self, price: float) -> float:
        return (price // self.tick_size) * self.tick_size

    def _ceil(self, price: float) -> float:
        return -((-price) // self.tick_size) * self.tick_size

    def decide(
        self,
        *,
        top: BookTop,
        alpha: AlphaEstimate,
        buy_toxicity: ToxicityEstimate,
        sell_toxicity: ToxicityEstimate,
        inventory_notional_usd: float,
        max_position_notional_usd: float,
        half_spread_bps: float,
    ) -> V21Decision:
        if not top.valid:
            raise ValueError("invalid top-of-book")
        if max_position_notional_usd <= 0:
            raise ValueError("max_position_notional_usd must be positive")
        if half_spread_bps <= 0:
            raise ValueError("half_spread_bps must be positive")

        inventory_fraction = max(
            -1.0,
            min(1.0, inventory_notional_usd / max_position_notional_usd),
        )
        inventory_shift = -inventory_fraction * self.inventory_penalty_bps
        reservation_shift = alpha.expected_move_bps + inventory_shift
        reservation = top.mid * (1.0 + reservation_shift / 10_000.0)

        raw_bid = reservation * (1.0 - half_spread_bps / 10_000.0)
        raw_ask = reservation * (1.0 + half_spread_bps / 10_000.0)

        # Improving the current BBO inside the spread is still passive.
        # A quote is marketable only when it crosses the opposite BBO.
        bid_cross = raw_bid >= top.ask_price - 1e-12
        ask_cross = raw_ask <= top.bid_price + 1e-12

        bid = None if bid_cross else self._floor(raw_bid)
        ask = None if ask_cross else self._ceil(raw_ask)

        if bid is not None and (bid >= top.ask_price or bid <= 0):
            bid = None
            bid_cross = True
        if ask is not None and (ask <= top.bid_price or ask <= 0):
            ask = None
            ask_cross = True
        if bid is not None and ask is not None and bid >= ask:
            bid = None
            ask = None
            bid_cross = True
            ask_cross = True

        bid_capture = (
            (top.mid - bid) * 10_000.0 / bid
            if bid is not None and bid > 0
            else 0.0
        )
        ask_capture = (
            (ask - top.mid) * 10_000.0 / ask
            if ask is not None and ask > 0
            else 0.0
        )

        bid_toxicity = buy_toxicity.expected_cost_bps
        ask_toxicity = sell_toxicity.expected_cost_bps

        bid_edge = (
            bid_capture
            + alpha.expected_move_bps
            - self.maker_fee_bps
            - bid_toxicity
        )
        ask_edge = (
            ask_capture
            - alpha.expected_move_bps
            - self.maker_fee_bps
            - ask_toxicity
        )

        bid_enabled = bid is not None and bid_edge >= self.min_edge_bps
        ask_enabled = ask is not None and ask_edge >= self.min_edge_bps

        reasons = []
        if bid_cross:
            reasons.append("bid_crossing_suppressed")
        if ask_cross:
            reasons.append("ask_crossing_suppressed")
        if not bid_enabled and not bid_cross:
            reasons.append("bid_edge_below_threshold")
        if not ask_enabled and not ask_cross:
            reasons.append("ask_edge_below_threshold")
        if not reasons:
            reasons.append("both_sides_eligible")

        return V21Decision(
            bid_price=bid if bid_enabled else None,
            ask_price=ask if ask_enabled else None,
            bid_enabled=bid_enabled,
            ask_enabled=ask_enabled,
            bid_edge_bps=bid_edge,
            ask_edge_bps=ask_edge,
            bid_toxicity_cost_bps=bid_toxicity,
            ask_toxicity_cost_bps=ask_toxicity,
            bid_crossing_request=bid_cross,
            ask_crossing_request=ask_cross,
            reservation_shift_bps=reservation_shift,
            reason=";".join(reasons),
        )
