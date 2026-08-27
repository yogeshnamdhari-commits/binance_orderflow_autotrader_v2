"""Execution layer — order-state management, duplicate protection, paper fills.

The LIVE execution path remains hard-locked (governance). The paper/testnet
path routes through OrderStateManager, which:
  - assigns a unique order id and rejects duplicate client ids (idempotency)
  - tracks the full order lifecycle:
        OPEN -> (PARTIAL) -> FILLED
        OPEN -> REJECTED / TIMEOUT / CANCELLED
  - simulates a paper fill at the touched price (buy@ask, sell@bid)
  - supports partial fills, rejections, timeouts and emergency close
  - can persist/restore state for safe restart (paper-grade recovery)

Observability: every state transition is optionally journaled via a callback
or app.journal.Journal instance.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import itertools
import json
from pathlib import Path


@dataclass
class ExecutionResult:
    status: str
    order_id: str | None
    message: str
    client_id: str | None = None


@dataclass
class OrderState:
    order_id: str
    client_id: str
    symbol: str
    side: str
    qty: float
    price: float
    # OPEN / FILLED / PARTIAL / CANCELLED / REJECTED / TIMEOUT
    status: str = "OPEN"
    filled_qty: float = 0.0
    avg_fill_price: float = 0.0
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self):
        return {
            "order_id": self.order_id, "client_id": self.client_id,
            "symbol": self.symbol, "side": self.side, "qty": self.qty,
            "price": self.price, "status": self.status,
            "filled_qty": self.filled_qty, "avg_fill_price": self.avg_fill_price,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(d["order_id"], d["client_id"], d["symbol"], d["side"],
                   d["qty"], d["price"], d.get("status", "OPEN"),
                   d.get("filled_qty", 0.0), d.get("avg_fill_price", 0.0),
                   d.get("created_at", ""), d.get("updated_at", ""))


class OrderStateManager:
    def __init__(self, journal=None):
        self._orders = {}
        self._by_client = {}
        self._seq = itertools.count(1)
        # journal: a callable(dict) or an object with .write(dict)
        self._log = journal.write if hasattr(journal, "write") else journal

    def _now(self):
        return datetime.now(timezone.utc).isoformat()

    def _emit(self, event, order=None, **kw):
        if self._log is None:
            return
        rec = {"event": event, "ts": self._now()}
        if order is not None:
            rec["order_id"] = order.order_id
            rec["client_id"] = order.client_id
            rec["status"] = order.status
        rec.update(kw)
        try:
            self._log(rec)
        except Exception:
            pass  # observability must never break the order path

    def duplicate(self, client_id):
        return client_id in self._by_client

    def create(self, symbol, side, qty, price, client_id=None):
        if client_id and self.duplicate(client_id):
            return None  # duplicate-order protection (idempotency)
        oid = "ORD-%d" % next(self._seq)
        if client_id is None:
            client_id = oid
        o = OrderState(oid, client_id, symbol, side, qty, price,
                       created_at=self._now(), updated_at=self._now())
        self._orders[oid] = o
        self._by_client[client_id] = oid
        self._emit("ORDER_CREATED", o)
        return o

    def get(self, order_id):
        return self._orders.get(order_id)

    def mark_filled(self, order_id, fill_price, fill_qty):
        o = self._orders.get(order_id)
        if o is None:
            return None
        o.filled_qty += fill_qty
        total = o.avg_fill_price * (o.filled_qty - fill_qty) + fill_price * fill_qty
        o.avg_fill_price = total / o.filled_qty if o.filled_qty > 0 else 0.0
        o.status = "FILLED" if abs(o.filled_qty - o.qty) < 1e-12 else "PARTIAL"
        o.updated_at = self._now()
        self._emit("ORDER_FILL", o, fill_price=fill_price, fill_qty=fill_qty)
        return o

    def mark_partial_fill(self, order_id, fill_price, fill_qty):
        """Explicit partial fill (accumulates toward full fill)."""
        return self.mark_filled(order_id, fill_price, fill_qty)

    def cancel(self, order_id):
        o = self._orders.get(order_id)
        if o is None or o.status in ("FILLED", "CANCELLED", "REJECTED", "TIMEOUT"):
            return o
        o.status = "CANCELLED"
        o.updated_at = self._now()
        self._emit("ORDER_CANCELLED", o)
        return o

    def reject(self, order_id, reason=""):
        o = self._orders.get(order_id)
        if o is None:
            return None
        o.status = "REJECTED"
        o.updated_at = self._now()
        self._emit("ORDER_REJECTED", o, reason=reason)
        return o

    def timeout_order(self, order_id, reason="timeout"):
        """Execution timeout: an unfilled/unacked order is dead -> TIMEOUT."""
        o = self._orders.get(order_id)
        if o is None or o.status in ("FILLED", "CANCELLED", "REJECTED", "TIMEOUT"):
            return o
        o.status = "TIMEOUT"
        o.updated_at = self._now()
        self._emit("ORDER_TIMEOUT", o, reason=reason)
        return o

    def emergency_close_all(self, reason="emergency"):
        closed = []
        for oid, o in self._orders.items():
            if o.status in ("OPEN", "PARTIAL"):
                o.status = "CANCELLED"
                o.updated_at = self._now()
                self._emit("ORDER_CANCELLED", o, reason="emergency")
                closed.append(oid)
        return closed

    @property
    def open_orders(self):
        return [o for o in self._orders.values() if o.status in ("OPEN", "PARTIAL")]

    def summary(self):
        return {
            "total": len(self._orders),
            "open": len(self.open_orders),
            "orders": [o.to_dict() for o in self._orders.values()],
        }

    # -- persistence (paper-grade restart recovery) --
    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([o.to_dict() for o in self._orders.values()],
                                    indent=2))
        return path

    def load(self, path):
        """Restore orders from a previous save().

        Missing file -> fresh start (safe for paper). Corrupt file ->
        treated as empty (never crash on restart). Duplicate client-id
        detection is rebuilt so restarts cannot create duplicate orders.
        Returns the number of orders restored.
        """
        path = Path(path)
        if not path.exists():
            return 0
        try:
            rows = json.loads(path.read_text())
        except (json.JSONDecodeError, ValueError):
            return 0  # corrupted/missing state -> start clean
        self._orders = {}
        self._by_client = {}
        for d in rows:
            o = OrderState.from_dict(d)
            self._orders[o.order_id] = o
            self._by_client[o.client_id] = o.order_id
        return len(self._orders)


class PaperExecution:
    """Paper execution: simulates immediate fill at the touched price.

    Fill price is conservative: a BUY rests/fills at best ASK, a SELL at best
    BID (crossing the spread, as an aggressive maker/taker would). The fill is
    recorded in the shared OrderStateManager so downstream risk/exposure can
    track it.
    """

    def __init__(self, manager=None, journal=None):
        self.manager = manager or OrderStateManager(journal)

    def _fill_at_touch(self, o, book, price):
        fill_price = price
        if book is not None:
            if o.side == "BUY":
                ba = book.state.best_ask()
                fill_price = ba if ba is not None else price
            else:
                bb = book.state.best_bid()
                fill_price = bb if bb is not None else price
        self.manager.mark_filled(o.order_id, fill_price, o.qty)
        return fill_price

    def submit(self, symbol, side, qty, price, client_id=None, book=None):
        if self.manager.duplicate(client_id):
            return ExecutionResult("REJECTED_DUPLICATE", None,
                                   "duplicate client_id=%s" % client_id, client_id)
        o = self.manager.create(symbol, side, qty, price, client_id)
        if o is None:
            return ExecutionResult("REJECTED_DUPLICATE", None,
                                   "duplicate client_id=%s" % client_id, client_id)
        fill_price = self._fill_at_touch(o, book, price)
        return ExecutionResult("PAPER_FILLED", o.order_id,
                               "%s %s %s @ %.2f" % (side, qty, symbol, fill_price),
                               client_id)

    def cancel(self, order_id):
        self.manager.cancel(order_id)
        return ExecutionResult("CANCELLED", order_id, "cancelled")

    def emergency_close_all(self, reason="emergency"):
        closed = self.manager.emergency_close_all(reason)
        return ExecutionResult("EMERGENCY_CLOSED", None,
                               "closed %d orders" % len(closed))


class SimulatedExchange(PaperExecution):
    """Configurable paper exchange for failure-injection / hardening tests.

    mode:
      'fill'    - immediate full fill at touch (default, same as PaperExecution)
      'reject'  - exchange rejects the order
      'partial' - fills exactly half, leaving the order PARTIAL
      'timeout' - order never acknowledges -> TIMEOUT
    """

    def __init__(self, manager=None, journal=None, mode="fill"):
        super().__init__(manager, journal)
        self.mode = mode

    def submit(self, symbol, side, qty, price, client_id=None, book=None):
        if self.manager.duplicate(client_id):
            return ExecutionResult("REJECTED_DUPLICATE", None,
                                   "duplicate client_id=%s" % client_id, client_id)
        o = self.manager.create(symbol, side, qty, price, client_id)
        if o is None:
            return ExecutionResult("REJECTED_DUPLICATE", None,
                                   "duplicate client_id=%s" % client_id, client_id)
        if self.mode == "reject":
            self.manager.reject(o.order_id, "simulated rejection")
            return ExecutionResult("REJECTED", o.order_id, "rejected", client_id)
        if self.mode == "partial":
            self.manager.mark_partial_fill(o.order_id, price, qty / 2.0)
            return ExecutionResult("PARTIAL_FILL", o.order_id, "partial fill", client_id)
        if self.mode == "timeout":
            self.manager.timeout_order(o.order_id, "simulated timeout")
            return ExecutionResult("TIMEOUT", o.order_id, "timeout", client_id)
        fill_price = self._fill_at_touch(o, book, price)
        return ExecutionResult("PAPER_FILLED", o.order_id,
                               "%s %s %s @ %.2f" % (side, qty, symbol, fill_price),
                               client_id)


class LiveExecution:
    def __init__(self, client):
        self.client = client

    def submit(self, *args, **kwargs):
        raise RuntimeError(
            "Live execution is locked OFF until authenticated order lifecycle "
            "+ user-stream reconciliation + validation gates pass.")
