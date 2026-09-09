from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from math import log1p


@dataclass(frozen=True)
class LiquidationEvent:
    timestamp_ns: int
    side: str
    quantity: float
    price: float


def compute_liquidation_features(
    events: Iterable[LiquidationEvent],
    now_ns: int,
    windows_ns: Sequence[int],
) -> dict[str, float]:
    """Signed liquidation intensity using only events at or before now_ns."""
    prior = [e for e in events if e.timestamp_ns <= now_ns and e.quantity >= 0]
    out: dict[str, float] = {}
    for window in windows_ns:
        if window <= 0:
            raise ValueError("liquidation windows must be positive")
        start = now_ns - window
        recent = [e for e in prior if e.timestamp_ns >= start]
        long_qty = sum(e.quantity for e in recent if e.side.upper() == "SELL")
        short_qty = sum(e.quantity for e in recent if e.side.upper() == "BUY")
        total = long_qty + short_qty
        out[f"liq_signed_{window}"] = (short_qty - long_qty) / total if total else 0.0
        out[f"liq_intensity_{window}"] = log1p(total)
    return out


def compute_funding_basis_features(
    funding_rate: float | None,
    mark_price: float | None,
    index_price: float | None,
) -> dict[str, float]:
    """Compute bounded carry/basis state; missing inputs remain neutral, never inferred."""
    if funding_rate is None:
        funding = 0.0
        funding_missing = 1.0
    else:
        funding = float(funding_rate)
        funding_missing = 0.0

    if mark_price is None or index_price is None or index_price <= 0:
        premium = 0.0
        premium_missing = 1.0
    else:
        premium = float(mark_price) / float(index_price) - 1.0
        premium_missing = 0.0

    return {
        "funding_rate": funding,
        "funding_missing": funding_missing,
        "mark_index_premium": premium,
        "premium_missing": premium_missing,
    }


def compute_cross_market_features(
    target_price: float,
    target_reference_price: float | None,
    lagged_spot_return: float | None,
    lagged_perpetual_return: float | None,
) -> dict[str, float]:
    """Use only lagged cross-market information; current target reference is optional."""
    spot = 0.0 if lagged_spot_return is None else float(lagged_spot_return)
    perp = 0.0 if lagged_perpetual_return is None else float(lagged_perpetual_return)
    if target_reference_price is None or target_reference_price <= 0 or target_price <= 0:
        basis = 0.0
        basis_missing = 1.0
    else:
        basis = target_price / target_reference_price - 1.0
        basis_missing = 0.0
    return {
        "lagged_spot_return": spot,
        "lagged_perpetual_return": perp,
        "cross_market_confirmation": 0.5 * (spot + perp),
        "cross_market_divergence": spot - perp,
        "target_reference_basis": basis,
        "target_reference_basis_missing": basis_missing,
    }
