"""Passive-order economics for V10 replay and OOS evaluation."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FillObservation:
    fill_time_ms: float
    filled: bool

    def __post_init__(self) -> None:
        if self.fill_time_ms <= 0:
            raise ValueError("fill_time_ms must be positive")


@dataclass(frozen=True)
class PassiveQuote:
    side: str
    price: float
    mid: float
    maker_fee_bps: float = 0.0

    def __post_init__(self) -> None:
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if self.price <= 0 or self.mid <= 0:
            raise ValueError("price and mid must be positive")
        if self.maker_fee_bps < 0:
            raise ValueError("maker_fee_bps must be non-negative")


def adverse_selection_bps(side: str, mid_before: float, mid_after: float) -> float:
    """Return adverse-selection cost in bps; positive means harmful."""
    if side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    if mid_before <= 0 or mid_after <= 0:
        raise ValueError("mid prices must be positive")
    signed_return_bps = (mid_after - mid_before) / mid_before * 10_000.0
    return -signed_return_bps if side == "BUY" else signed_return_bps


def passive_order_ev_bps(
    quote: PassiveQuote,
    *,
    fill_probability: float,
    adverse_selection_cost_bps: float,
    other_cost_bps: float = 0.0,
) -> float:
    """Expected P&L per submitted unit in bps."""
    if not 0.0 <= fill_probability <= 1.0:
        raise ValueError("fill_probability must be in [0, 1]")
    if adverse_selection_cost_bps < 0 or other_cost_bps < 0:
        raise ValueError("costs must be non-negative")

    half_spread_bps = abs(quote.mid - quote.price) / quote.mid * 10_000.0
    conditional_ev = (
        half_spread_bps
        - quote.maker_fee_bps
        - adverse_selection_cost_bps
        - other_cost_bps
    )
    return fill_probability * conditional_ev
