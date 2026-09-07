"""V12 order manager — complete order lifecycle management.

CREATE -> SUBMIT -> ACK -> PARTIAL -> FILLED
                        -> CANCEL -> REJECT -> EXPIRE -> RECONCILE

Persists every state transition.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import uuid


class OrderStatus(Enum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"
    STOP_LIMIT = "STOP_LIMIT"


@dataclass
class V12Order:
    """Complete order state."""
    order_id: str
    client_id: str
    exchange_id: str | None = None
    ts_created: int = 0
    ts_submitted: int = 0
    ts_filled: int = 0
    ts_cancelled: int = 0
    side: str = ""  # BUY/SELL
    qty_btc: float = 0.0
    filled_qty_btc: float = 0.0
    price: float = 0.0
    avg_fill_price: float = 0.0
    order_type: OrderType = OrderType.MARKET
    reduce_only: bool = False
    status: OrderStatus = OrderStatus.CREATED
    expected_edge_bps: float = 0.0
    actual_fees_bps: float = 0.0
    actual_slippage_bps: float = 0.0
    latency_ms: int = 0
    reject_reason: str = ""
    events: list[dict] = field(default_factory=list)


class V12OrderManager:
    """Manages complete order lifecycle."""

    def __init__(self):
        self._orders: dict[str, V12Order] = {}
        self._by_client: dict[str, str] = {}
        self._seq = 0

    def _now_ms(self) -> int:
        return int(datetime.now(timezone.utc).timestamp() * 1000)

    def _emit(self, order: V12Order, event: str, **kwargs):
        evt = {"event": event, "ts": self._now_ms(), "order_id": order.order_id, "client_id": order.client_id}
        evt.update(kwargs)
        order.events.append(evt)

    def create_order(
        self,
        client_id: str,
        side: str,
        qty_btc: float,
        price: float,
        order_type: OrderType = OrderType.MARKET,
        reduce_only: bool = False,
        expected_edge_bps: float = 0.0,
    ) -> V12Order | None:
        """Create new order with duplicate protection."""
        if client_id in self._by_client:
            return None  # duplicate protection

        self._seq += 1
        order = V12Order(
            order_id=f"ORD-{self._seq:06d}",
            client_id=client_id,
            side=side.upper(),
            qty_btc=qty_btc,
            price=price,
            order_type=order_type,
            reduce_only=reduce_only,
            expected_edge_bps=expected_edge_bps,
            status=OrderStatus.CREATED,
            ts_created=self._now_ms(),
        )
        self._orders[order.order_id] = order
        self._by_client[client_id] = order.order_id
        self._emit(order, "CREATED")
        return order

    def submit(self, order_id: str) -> bool:
        """Mark order as submitted."""
        order = self._orders.get(order_id)
        if not order or order.status != OrderStatus.CREATED:
            return False
        order.status = OrderStatus.SUBMITTED
        order.ts_submitted = self._now_ms()
        self._emit(order, "SUBMITTED")
        return True

    def acknowledge(self, order_id: str, exchange_id: str) -> bool:
        """Mark order as acknowledged by exchange."""
        order = self._orders.get(order_id)
        if not order or order.status != OrderStatus.SUBMITTED:
            return False
        order.status = OrderStatus.ACKNOWLEDGED
        order.exchange_id = exchange_id
        self._emit(order, "ACKNOWLEDGED")
        return True

    def fill(self, order_id: str, fill_price: float, fill_qty: float, fees_bps: float = 0.0, slippage_bps: float = 0.0) -> V12Order | None:
        """Record fill (full or partial)."""
        order = self._orders.get(order_id)
        if not order or order.status not in (OrderStatus.SUBMITTED, OrderStatus.ACKNOWLEDGED, OrderStatus.PARTIAL):
            return None

        order.filled_qty_btc += fill_qty
        # Update average fill price
        total = order.avg_fill_price * (order.filled_qty_btc - fill_qty) + fill_price * fill_qty
        order.avg_fill_price = total / order.filled_qty_btc if order.filled_qty_btc > 0 else 0.0
        order.actual_fees_bps = fees_bps
        order.actual_slippage_bps = slippage_bps

        if abs(order.filled_qty_btc - order.qty_btc) < 1e-12:
            order.status = OrderStatus.FILLED
            order.ts_filled = self._now_ms()
            self._emit(order, "FILLED", fill_price=fill_price, fill_qty=fill_qty)
        else:
            order.status = OrderStatus.PARTIAL
            self._emit(order, "PARTIAL_FILL", fill_price=fill_price, fill_qty=fill_qty)

        return order

    def cancel(self, order_id: str) -> bool:
        """Cancel order."""
        order = self._orders.get(order_id)
        if not order or order.status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED):
            return False
        order.status = OrderStatus.CANCELLED
        order.ts_cancelled = self._now_ms()
        self._emit(order, "CANCELLED")
        return True

    def reject(self, order_id: str, reason: str) -> bool:
        """Reject order."""
        order = self._orders.get(order_id)
        if not order:
            return False
        order.status = OrderStatus.REJECTED
        order.reject_reason = reason
        self._emit(order, "REJECTED", reason=reason)
        return True

    def expire(self, order_id: str) -> bool:
        """Expire order (timeout)."""
        order = self._orders.get(order_id)
        if not order or order.status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED):
            return False
        order.status = OrderStatus.EXPIRED
        self._emit(order, "EXPIRED")
        return True

    def get(self, order_id: str) -> V12Order | None:
        return self._orders.get(order_id)

    def get_by_client(self, client_id: str) -> V12Order | None:
        oid = self._by_client.get(client_id)
        return self._orders.get(oid) if oid else None

    def open_orders(self) -> list[V12Order]:
        return [o for o in self._orders.values() if o.status in (OrderStatus.CREATED, OrderStatus.SUBMITTED, OrderStatus.ACKNOWLEDGED, OrderStatus.PARTIAL)]

    def persist(self, path: Path) -> Path:
        """Persist all orders to JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {oid: {
            "order_id": o.order_id,
            "client_id": o.client_id,
            "exchange_id": o.exchange_id,
            "ts_created": o.ts_created,
            "ts_submitted": o.ts_submitted,
            "ts_filled": o.ts_filled,
            "ts_cancelled": o.ts_cancelled,
            "side": o.side,
            "qty_btc": o.qty_btc,
            "filled_qty_btc": o.filled_qty_btc,
            "price": o.price,
            "avg_fill_price": o.avg_fill_price,
            "order_type": o.order_type.value,
            "reduce_only": o.reduce_only,
            "status": o.status.value,
            "expected_edge_bps": o.expected_edge_bps,
            "actual_fees_bps": o.actual_fees_bps,
            "actual_slippage_bps": o.actual_slippage_bps,
            "latency_ms": o.latency_ms,
            "reject_reason": o.reject_reason,
            "events": o.events,
        } for oid, o in self._orders.items()}
        path.write_text(json.dumps(data, indent=2))
        return path

    @classmethod
    def load(cls, path: Path) -> "V12OrderManager":
        mgr = cls()
        if not path.exists():
            return mgr
        data = json.loads(path.read_text())
        for oid, d in data.items():
            o = V12Order(
                order_id=d["order_id"],
                client_id=d["client_id"],
                exchange_id=d.get("exchange_id"),
                ts_created=d["ts_created"],
                ts_submitted=d["ts_submitted"],
                ts_filled=d["ts_filled"],
                ts_cancelled=d["ts_cancelled"],
                side=d["side"],
                qty_btc=d["qty_btc"],
                filled_qty_btc=d["filled_qty_btc"],
                price=d["price"],
                avg_fill_price=d["avg_fill_price"],
                order_type=OrderType(d["order_type"]),
                reduce_only=d["reduce_only"],
                status=OrderStatus(d["status"]),
                expected_edge_bps=d["expected_edge_bps"],
                actual_fees_bps=d["actual_fees_bps"],
                actual_slippage_bps=d["actual_slippage_bps"],
                latency_ms=d["latency_ms"],
                reject_reason=d["reject_reason"],
                events=d["events"],
            )
            mgr._orders[oid] = o
            mgr._by_client[d["client_id"]] = oid
            mgr._seq = max(mgr._seq, int(oid.split("-")[1]) if "-" in oid else 0)
        return mgr