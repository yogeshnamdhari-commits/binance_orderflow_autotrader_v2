from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class LocalOrder:
    client_id: str
    order_id: str | None
    symbol: str
    side: str
    qty: float
    filled_qty: float
    status: str


@dataclass(frozen=True)
class ExchangeOrder:
    client_id: str
    order_id: str | None
    symbol: str
    side: str
    qty: float
    filled_qty: float
    status: str


@dataclass(frozen=True)
class PositionState:
    symbol: str
    quantity: float


@dataclass(frozen=True)
class ReconciliationResult:
    ok: bool
    reasons: tuple[str, ...]
    local_open_orders: int
    exchange_open_orders: int
    local_position: float
    exchange_position: float


_TERMINAL = {"FILLED", "CANCELLED", "REJECTED", "EXPIRED", "TIMEOUT"}


def reconcile(
    local_orders: Mapping[str, LocalOrder],
    exchange_orders: Mapping[str, ExchangeOrder],
    local_position: PositionState,
    exchange_position: PositionState,
    qty_tolerance: float = 1e-9,
) -> ReconciliationResult:
    reasons: list[str] = []

    local_open = {k: v for k, v in local_orders.items() if v.status not in _TERMINAL}
    exchange_open = {k: v for k, v in exchange_orders.items() if v.status not in _TERMINAL}

    for cid, order in local_open.items():
        other = exchange_open.get(cid)
        if other is None:
            reasons.append(f"missing_exchange_order:{cid}")
            continue
        if order.symbol != other.symbol or order.side != other.side:
            reasons.append(f"order_identity_mismatch:{cid}")
        if abs(order.qty - other.qty) > qty_tolerance:
            reasons.append(f"order_qty_mismatch:{cid}")
        if abs(order.filled_qty - other.filled_qty) > qty_tolerance:
            reasons.append(f"order_fill_mismatch:{cid}")
        if order.status != other.status:
            reasons.append(f"order_status_mismatch:{cid}:{order.status}!={other.status}")

    for cid in exchange_open:
        if cid not in local_open:
            reasons.append(f"unexpected_exchange_order:{cid}")

    if local_position.symbol != exchange_position.symbol:
        reasons.append("position_symbol_mismatch")
    if abs(local_position.quantity - exchange_position.quantity) > qty_tolerance:
        reasons.append("position_quantity_mismatch")

    return ReconciliationResult(
        ok=not reasons,
        reasons=tuple(reasons),
        local_open_orders=len(local_open),
        exchange_open_orders=len(exchange_open),
        local_position=local_position.quantity,
        exchange_position=exchange_position.quantity,
    )
