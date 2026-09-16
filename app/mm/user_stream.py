from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OrderUpdate:
    symbol: str
    client_id: str
    order_id: str
    side: str
    status: str
    execution_type: str
    qty: float
    filled_qty: float
    avg_price: float
    last_fill_qty: float
    last_fill_price: float
    trade_id: str
    commission: float
    commission_asset: str
    event_ts_ms: int


@dataclass(frozen=True)
class PositionUpdate:
    symbol: str
    quantity: float
    entry_price: float
    unrealized_pnl: float
    event_ts_ms: int


class UserStreamGuard:
    """Track private-stream health using events plus transport heartbeats.

    An otherwise healthy account stream can be silent for many seconds. Health
    therefore cannot depend on trading events alone. Successful WebSocket
    heartbeat/pong activity refreshes the transport timestamp.
    """

    def __init__(self, max_age_ms: int = 5000) -> None:
        self.max_age_ms = int(max_age_ms)
        self.last_activity_ts_ms: int | None = None
        self.connected = False

    @property
    def last_event_ts_ms(self) -> int | None:
        """Backward-compatible name for the latest transport activity."""
        return self.last_activity_ts_ms

    def connected_event(self, event_ts_ms: int) -> None:
        self.connected = True
        self.last_activity_ts_ms = int(event_ts_ms)

    def heartbeat(self, now_ms: int) -> None:
        """Record successful WebSocket transport activity."""
        if self.connected:
            self.last_activity_ts_ms = int(now_ms)

    def disconnected(self) -> None:
        self.connected = False

    def health(self, now_ms: int) -> tuple[bool, int, str]:
        if not self.connected or self.last_activity_ts_ms is None:
            return False, 10**9, "disconnected"
        age = max(0, int(now_ms) - self.last_activity_ts_ms)
        return age <= self.max_age_ms, age, "ok" if age <= self.max_age_ms else "stale"

    def parse(self, payload: dict[str, Any]) -> tuple[OrderUpdate | PositionUpdate, ...]:
        event = payload.get("e")
        event_ts = int(payload.get("E", 0))
        self.connected_event(event_ts)
        if event == "ORDER_TRADE_UPDATE":
            o = payload.get("o", {})
            return (OrderUpdate(
                symbol=str(o.get("s", "")),
                client_id=str(o.get("c", "")),
                order_id=str(o.get("i", "")),
                side=str(o.get("S", "")),
                status=str(o.get("X", "")),
                execution_type=str(o.get("x", "")),
                qty=float(o.get("q", 0) or 0),
                filled_qty=float(o.get("z", 0) or 0),
                avg_price=float(o.get("ap", 0) or 0),
                last_fill_qty=float(o.get("l", 0) or 0),
                last_fill_price=float(o.get("L", 0) or 0),
                trade_id=str(o.get("t", "")),
                commission=float(o.get("n", 0) or 0),
                commission_asset=str(o.get("N", "")),
                event_ts_ms=event_ts,
            ),)
        if event == "ACCOUNT_UPDATE":
            account = payload.get("a", {})
            out: list[PositionUpdate] = []
            for row in account.get("P", []) or []:
                out.append(PositionUpdate(
                    symbol=str(row.get("s", "")),
                    quantity=float(row.get("pa", 0) or 0),
                    entry_price=float(row.get("ep", 0) or 0),
                    unrealized_pnl=float(row.get("up", 0) or 0),
                    event_ts_ms=event_ts,
                ))
            return tuple(out)
        if event in {"listenKeyExpired", "MARGIN_CALL"}:
            self.connected = False
            return ()
        raise ValueError(f"unrecognized_user_event:{event}")
