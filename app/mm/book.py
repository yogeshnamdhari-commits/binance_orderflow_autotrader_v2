from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class L2Snapshot:
    """Authoritative USD-M depth snapshot."""

    timestamp_ns: int
    last_update_id: int
    bids: list[tuple[float, float]]
    asks: list[tuple[float, float]]
    bridge_complete: bool = False


@dataclass
class L2Update:
    """Incremental USD-M diff-depth update."""

    timestamp_ns: int
    first_update_id: int
    final_update_id: int
    prev_final_update_id: int | None
    bids: list[tuple[float, float]]
    asks: list[tuple[float, float]]


@dataclass
class OrderBook:
    """Fail-closed local order book with strict Binance sequence validation.

    Bootstrap follows the Binance snapshot + diff-depth procedure:
      first accepted event satisfies U <= snapshot_last_update_id + 1 <= u
      subsequent events satisfy pu == previous u
    """

    timestamp_ns: int
    last_update_id: int
    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)
    _awaiting_first_diff: bool = field(default=True, repr=False, compare=False)

    @classmethod
    def from_snapshot(cls, snapshot: L2Snapshot) -> "OrderBook":
        book = cls(
            timestamp_ns=int(snapshot.timestamp_ns),
            last_update_id=int(snapshot.last_update_id),
            _awaiting_first_diff=not snapshot.bridge_complete,
        )
        for price, qty in snapshot.bids:
            p, q = float(price), float(qty)
            if q > 0:
                book.bids[p] = q
        for price, qty in snapshot.asks:
            p, q = float(price), float(qty)
            if q > 0:
                book.asks[p] = q
        if snapshot.bridge_complete and not book.is_valid():
            raise ValueError("invalid snapshot book")
        return book

    def apply_update(self, update: L2Update) -> None:
        if self.last_update_id is None:
            raise ValueError("snapshot required before depth updates")

        U = int(update.first_update_id)
        u = int(update.final_update_id)
        pu = None if update.prev_final_update_id is None else int(update.prev_final_update_id)

        if U > u:
            raise ValueError(f"invalid depth sequence U={U} > u={u}")

        if u <= self.last_update_id:
            return

        expected = self.last_update_id + 1

        if self._awaiting_first_diff:
            if not (U <= expected <= u):
                raise ValueError(
                    "initial depth bridge invalid: "
                    f"expected={expected}, U={U}, u={u}"
                )
            self._awaiting_first_diff = False
        else:
            if pu is None:
                raise ValueError(
                    f"depth sequence invalid: missing pu after bootstrap; "
                    f"previous_u={self.last_update_id}, U={U}, u={u}"
                )
            if pu != self.last_update_id:
                raise ValueError(
                    f"depth sequence gap: expected pu={self.last_update_id}, "
                    f"got pu={pu}, U={U}, u={u}"
                )

        for price, qty in update.bids:
            p, q = float(price), float(qty)
            if q == 0:
                self.bids.pop(p, None)
            elif q > 0:
                self.bids[p] = q
            else:
                raise ValueError(f"negative bid quantity: {q}")

        for price, qty in update.asks:
            p, q = float(price), float(qty)
            if q == 0:
                self.asks.pop(p, None)
            elif q > 0:
                self.asks[p] = q
            else:
                raise ValueError(f"negative ask quantity: {q}")

        self.last_update_id = u
        self.timestamp_ns = int(update.timestamp_ns)

        if not self.is_valid():
            raise ValueError("book crossed or empty after depth update")

    def is_valid(self) -> bool:
        if not self.bids or not self.asks:
            return False
        return max(self.bids) < min(self.asks)

    def get_mid_price(self) -> float:
        if not self.is_valid():
            return 0.0
        return (max(self.bids) + min(self.asks)) / 2.0

    def get_spread_bps(self) -> float:
        if not self.is_valid():
            return 0.0
        bid, ask = max(self.bids), min(self.asks)
        mid = (bid + ask) / 2.0
        return (ask - bid) * 10_000.0 / mid if mid > 0 else 0.0

    def get_depth(self, side: str, levels: int = 10) -> list[tuple[float, float]]:
        if side == "bid":
            prices = sorted(self.bids.keys(), reverse=True)[:levels]
            return [(p, self.bids[p]) for p in prices]
        if side == "ask":
            prices = sorted(self.asks.keys())[:levels]
            return [(p, self.asks[p]) for p in prices]
        raise ValueError("side must be 'bid' or 'ask'")

    def get_total_depth_qty(self, side: str, levels: int = 10) -> float:
        return sum(qty for _, qty in self.get_depth(side, levels))
