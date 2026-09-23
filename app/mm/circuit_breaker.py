from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker thresholds."""

    max_spread_bps: float = 5.0
    min_total_depth_qty: float = 1.0
    max_price_gap_bps: float = 10.0
    max_position_notional: float = 5000.0
    max_inventory_units: float = 0.5


class CircuitBreaker:
    """Monitor market conditions and kill quoting if they're extreme."""

    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
        self.last_mid_price = 0.0
        self.breaker_active = False
        self.breaker_reason = ""

    def should_quote(
        self,
        mid_price: float,
        spread_bps: float,
        total_depth_qty: float,
        position: float,
        current_price: float,
    ) -> tuple[bool, str]:
        """
        Check if we should quote.
        """

        if spread_bps > self.config.max_spread_bps:
            return False, f"spread_too_wide ({spread_bps:.2f} > {self.config.max_spread_bps})"

        if total_depth_qty < self.config.min_total_depth_qty:
            return False, f"insufficient_depth ({total_depth_qty:.4f} < {self.config.min_total_depth_qty})"

        if self.last_mid_price > 0:
            price_gap_bps = abs(mid_price - self.last_mid_price) * 10_000.0 / self.last_mid_price
            if price_gap_bps > self.config.max_price_gap_bps:
                return False, f"price_gap ({price_gap_bps:.2f} > {self.config.max_price_gap_bps})"

        position_notional = abs(position) * current_price
        if position_notional > self.config.max_position_notional:
            return False, f"position_too_large ({position_notional:.0f} > {self.config.max_position_notional})"

        if abs(position) > self.config.max_inventory_units:
            return False, f"inventory_breach ({abs(position):.4f} > {self.config.max_inventory_units})"

        self.last_mid_price = mid_price
        return True, "ok"
