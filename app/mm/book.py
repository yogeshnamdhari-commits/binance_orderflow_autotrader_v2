from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence
import numpy as np


@dataclass
class L2Snapshot:
    """Order book snapshot from REST API."""

    timestamp_ns: int
    last_update_id: int
    bids: list[tuple[float, float]]
    asks: list[tuple[float, float]]


@dataclass
class L2Update:
    """Incremental depth update from WebSocket."""

    timestamp_ns: int
    first_update_id: int
    final_update_id: int
    prev_final_update_id: int
    bids: list[tuple[float, float]]
    asks: list[tuple[float, float]]


@dataclass
class OrderBook:
    """Reconstructed order book with validation."""

    timestamp_ns: int
    last_update_id: int
    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)
    _awaiting_first_diff: bool = True

    @classmethod
    def from_snapshot(cls, snapshot: L2Snapshot) -> OrderBook:
        """Initialize from REST snapshot."""
        book = cls(
            timestamp_ns=snapshot.timestamp_ns,
            last_update_id=snapshot.last_update_id,
        )
        for price, qty in snapshot.bids:
            book.bids[float(price)] = float(qty)
        for price, qty in snapshot.asks:
            book.asks[float(price)] = float(qty)
        return book

    def apply_update(self, update: L2Update) -> None:
        """Apply incremental WebSocket update."""

        if self.last_update_id is None:
            raise ValueError("OrderBook must be initialized from snapshot before applying updates")

        # Binance's first diff-depth event must bracket the snapshot lastUpdateId.
        # After that one bridge event, every subsequent event must have pu == prior u.
        if update.final_update_id <= self.last_update_id:
            return

        if self._awaiting_first_diff:
            if not (update.first_update_id <= self.last_update_id <= update.final_update_id):
                raise ValueError(
                    "Initial depth bridge invalid: "
                    f"snapshot={self.last_update_id}, U={update.first_update_id}, "
                    f"u={update.final_update_id}"
                )
            self._awaiting_first_diff = False
        elif update.prev_final_update_id != self.last_update_id:
            raise ValueError(
                f"Sequence gap: expected pu={self.last_update_id}, "
                f"got pu={update.prev_final_update_id}"
            )

        for price, qty in update.bids:
            price = float(price)
            qty = float(qty)
            if qty == 0:
                self.bids.pop(price, None)
            else:
                self.bids[price] = qty

        for price, qty in update.asks:
            price = float(price)
            qty = float(qty)
            if qty == 0:
                self.asks.pop(price, None)
            else:
                self.asks[price] = qty

        self.last_update_id = update.final_update_id
        self.timestamp_ns = update.timestamp_ns

        if not self.is_valid():
            raise ValueError("Book is crossed or invalid after update")

    def is_valid(self) -> bool:
        """Check if book state is valid."""
        if not self.bids or not self.asks:
            return False

        best_bid = max(self.bids.keys())
        best_ask = min(self.asks.keys())

        if best_bid >= best_ask:
            return False

        return True

    def get_mid_price(self) -> float:
        """Get mid-price."""
        if not self.is_valid():
            return 0.0
        best_bid = max(self.bids.keys())
        best_ask = min(self.asks.keys())
        return (best_bid + best_ask) / 2.0

    def get_spread_bps(self) -> float:
        """Get spread in bps."""
        if not self.is_valid():
            return 0.0
        best_bid = max(self.bids.keys())
        best_ask = min(self.asks.keys())
        mid = (best_bid + best_ask) / 2.0
        return (best_ask - best_bid) * 10_000.0 / mid

    def get_depth(self, side: str, levels: int = 10) -> list[tuple[float, float]]:
        """Get depth levels."""
        if side == "bid":
            prices = sorted(self.bids.keys(), reverse=True)[:levels]
            return [(p, self.bids[p]) for p in prices]
        else:
            prices = sorted(self.asks.keys())[:levels]
            return [(p, self.asks[p]) for p in prices]

    def get_total_depth_qty(self, side: str, levels: int = 10) -> float:
        """Get total quantity at top N levels."""
        depth = self.get_depth(side, levels)
        return sum(qty for _, qty in depth)
