"""Paper-trade reconciliation utilities.

Pure, deterministic functions for reconciling local order/position state
against exchange state (or mock exchange state for paper trading).
No network calls, no side effects — pure logic suitable for unit testing
and for integration into paper trading lifecycle.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReconcileResult:
    """Result of reconciling local orders against exchange state."""
    matched: list = field(default_factory=list)         # local & exchange agree
    local_only: list = field(default_factory=list)      # in local, not on exchange
    exchange_only: list = field(default_factory=list)   # on exchange, unknown locally
    partial_mismatch: list = field(default_factory=list)  # filled_qty differs
    duplicate_client_ids: list = field(default_factory=list)
    stale_local: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "matched": self.matched,
            "local_only": self.local_only,
            "exchange_only": self.exchange_only,
            "partial_mismatch": self.partial_mismatch,
            "duplicate_client_ids": self.duplicate_client_ids,
            "stale_local": self.stale_local,
        }


def _normalize_local_order(o: Any) -> dict:
    """Normalize local order (OrderState or dict) to dict with standard keys."""
    if hasattr(o, "to_dict"):
        d = o.to_dict()
    else:
        d = dict(o)
    return {
        "order_id": d.get("order_id"),
        "client_id": d.get("client_id"),
        "symbol": d.get("symbol"),
        "side": d.get("side"),
        "qty": float(d.get("qty", 0)),
        "price": float(d.get("price", 0)),
        "filled_qty": float(d.get("filled_qty", 0)),
        "status": d.get("status", "OPEN"),
        "updated_at": d.get("updated_at", ""),
    }


def _normalize_exchange_order(e: dict) -> dict:
    """Normalize exchange order dict to standard keys."""
    return {
        "order_id": str(e.get("orderId", e.get("order_id", ""))),
        "client_id": e.get("clientOrderId", e.get("client_id", "")),
        "symbol": e.get("symbol", ""),
        "side": e.get("side", ""),
        "qty": float(e.get("origQty", e.get("qty", 0))),
        "price": float(e.get("price", 0)),
        "filled_qty": float(e.get("executedQty", e.get("filled_qty", 0))),
        "status": e.get("status", ""),
    }


def reconcile_orders(
    local_orders: list,
    exchange_orders: list,
    now_ms: int | None = None,
    stale_ms: int | None = None,
) -> ReconcileResult:
    """Reconcile local open orders against exchange open orders.

    Args:
        local_orders: list of OrderState or dicts with keys:
            order_id, client_id, symbol, side, qty, filled_qty, status, updated_at
        exchange_orders: list of dicts with keys:
            orderId, clientOrderId, symbol, side, origQty, executedQty, status
        now_ms: current time in milliseconds (for stale detection)
        stale_ms: threshold in ms for stale order detection

    Returns:
        ReconcileResult with categorized orders.
    """
    res = ReconcileResult()
    local_norm = [_normalize_local_order(o) for o in local_orders]
    ex_norm = [_normalize_exchange_order(e) for e in exchange_orders]

    # Index exchange orders by order_id and client_order_id
    ex_by_oid = {str(e["order_id"]): e for e in ex_norm if e.get("order_id")}
    ex_by_cid = {e["client_id"]: e for e in ex_norm if e.get("client_id")}

    seen_client_ids = set()

    for lo in local_norm:
        oid = str(lo["order_id"])
        cid = lo.get("client_id")
        ex = ex_by_oid.get(oid) or (ex_by_cid.get(cid) if cid else None)

        # Track duplicate client IDs
        if cid:
            if cid in seen_client_ids:
                res.duplicate_client_ids.append(oid)
            seen_client_ids.add(cid)

        if ex is None:
            res.local_only.append(oid)
            continue

        # Partial fill mismatch
        lo_filled = float(lo.get("filled_qty", 0) or 0)
        ex_filled = float(ex.get("filled_qty", 0) or 0)
        if abs(ex_filled - lo_filled) > 1e-9:
            res.partial_mismatch.append({
                "order_id": oid,
                "local_filled": lo_filled,
                "exchange_filled": ex_filled,
            })
        res.matched.append(oid)

    # Exchange orders not present locally -> unknown/exchange-only
    local_oids = {str(_normalize_local_order(o).get("order_id")) for o in local_orders}
    for e in ex_norm:
        if str(e.get("order_id")) not in local_oids:
            res.exchange_only.append(str(e.get("order_id")))

    # Stale local state detection
    if now_ms is not None and stale_ms is not None:
        for lo in local_norm:
            lu = lo.get("updated_at")
            if lu:
                try:
                    # Parse ISO timestamp to ms
                    from datetime import datetime, timezone
                    dt = datetime.fromisoformat(lu.replace("Z", "+00:00"))
                    lu_ms = int(dt.timestamp() * 1000)
                    if (now_ms - lu_ms) > stale_ms:
                        res.stale_local.append(str(lo["order_id"]))
                except Exception:
                    pass  # ignore parse errors

    return res


def reconcile_positions(local_pos: float, exchange_pos: float) -> dict:
    """Compare local tracked position vs exchange position."""
    lp = float(local_pos or 0.0)
    ep = float(exchange_pos or 0.0)
    diff = round(ep - lp, 8)
    return {
        "local": lp,
        "exchange": ep,
        "diff": diff,
        "mismatch": abs(diff) > 1e-9,
    }


def categorize_order_lifecycle(status: str) -> str:
    """Categorize order status into lifecycle phase."""
    if status in ("OPEN", "PARTIAL"):
        return "active"
    if status in ("FILLED",):
        return "terminal_filled"
    if status in ("CANCELLED", "REJECTED", "TIMEOUT"):
        return "terminal_other"
    return "unknown"


def is_terminal_status(status: str) -> bool:
    """Check if order status is terminal (no further updates expected)."""
    return status in ("FILLED", "CANCELLED", "REJECTED", "TIMEOUT")


def can_transition(from_status: str, to_status: str) -> bool:
    """Validate order state transition."""
    transitions = {
        "OPEN": {"PARTIAL", "FILLED", "CANCELLED", "REJECTED", "TIMEOUT"},
        "PARTIAL": {"PARTIAL", "FILLED", "CANCELLED", "REJECTED", "TIMEOUT"},
        "FILLED": set(),
        "CANCELLED": set(),
        "REJECTED": set(),
        "TIMEOUT": set(),
    }
    return to_status in transitions.get(from_status, set())


__all__ = [
    "ReconcileResult",
    "reconcile_orders",
    "reconcile_positions",
    "categorize_order_lifecycle",
    "is_terminal_status",
    "can_transition",
]