from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ForceOrder:
    event_time_ms: int
    symbol: str
    side: str
    order_type: str
    price: float
    quantity: float
    average_price: float


def parse_force_order(message: Mapping[str, Any]) -> ForceOrder:
    """Parse Binance USDⓈ-M forceOrder stream payload without inventing fields."""
    payload = message.get("o", message)
    required = ("E", "s", "S", "o", "p", "q", "ap")
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"forceOrder payload missing fields: {', '.join(missing)}")
    return ForceOrder(
        event_time_ms=int(payload["E"]),
        symbol=str(payload["s"]),
        side=str(payload["S"]),
        order_type=str(payload["o"]),
        price=float(payload["p"]),
        quantity=float(payload["q"]),
        average_price=float(payload["ap"]),
    )


def force_order_feature(event: ForceOrder, now_ms: int) -> dict[str, float]:
    if event.event_time_ms > now_ms:
        raise ValueError("future force-order event cannot enter a decision-time feature")
    signed_quantity = event.quantity if event.side.upper() == "BUY" else -event.quantity
    return {
        "liquidation_signed_qty": signed_quantity,
        "liquidation_abs_qty": abs(event.quantity),
        "liquidation_age_ms": float(now_ms - event.event_time_ms),
    }
