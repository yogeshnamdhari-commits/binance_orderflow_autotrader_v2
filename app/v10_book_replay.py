"""Deterministic research-only Binance L2 snapshot + diff-depth replay."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any, Iterable


class ReplayStatus(str, Enum):
    OK = "OK"
    INVALID_SNAPSHOT = "INVALID_SNAPSHOT"
    NO_BRIDGING_EVENT = "NO_BRIDGING_EVENT"
    GAP = "GAP"
    MALFORMED = "MALFORMED"


@dataclass(frozen=True)
class ReplayResult:
    status: ReplayStatus
    last_update_id: int | None
    bids: dict[Decimal, Decimal]
    asks: dict[Decimal, Decimal]
    reason: str | None = None


class V10BookReplay:
    """Replay Binance diff-depth events deterministically from a REST snapshot.

    The replay is deliberately independent of the production trading path. It
    uses Decimal for price/quantity preservation and treats sequence-integrity
    failures as explicit research failures rather than silently repairing them.
    """

    def replay(self, snapshot: dict[str, Any], events: Iterable[dict[str, Any]]) -> ReplayResult:
        try:
            snapshot_id = int(snapshot["lastUpdateId"])
            bids = self._levels(snapshot["bids"])
            asks = self._levels(snapshot["asks"])
        except (KeyError, TypeError, ValueError):
            return ReplayResult(ReplayStatus.INVALID_SNAPSHOT, None, {}, {}, "INVALID_SNAPSHOT")

        pending = list(events)
        first_index = None
        for i, event in enumerate(pending):
            try:
                u = int(event["u"])
            except (KeyError, TypeError, ValueError):
                return ReplayResult(ReplayStatus.MALFORMED, snapshot_id, bids, asks, "INVALID_EVENT_SEQUENCE")
            if u <= snapshot_id:
                continue
            first_index = i
            break

        if first_index is None:
            return ReplayResult(
                ReplayStatus.NO_BRIDGING_EVENT,
                snapshot_id,
                bids,
                asks,
                "NO_EVENT_AFTER_SNAPSHOT",
            )

        first = pending[first_index]
        try:
            first_U = int(first["U"])
            first_u = int(first["u"])
            first_pu = first.get("pu")
            first_pu = int(first_pu) if first_pu is not None else None
        except (KeyError, TypeError, ValueError):
            return ReplayResult(ReplayStatus.MALFORMED, snapshot_id, bids, asks, "INVALID_EVENT_SEQUENCE")

        if not (first_U <= snapshot_id + 1 <= first_u):
            return ReplayResult(
                ReplayStatus.NO_BRIDGING_EVENT,
                snapshot_id,
                bids,
                asks,
                "FIRST_EVENT_DOES_NOT_BRIDGE_SNAPSHOT",
            )
        if first_pu is not None and first_pu != snapshot_id:
            return ReplayResult(ReplayStatus.GAP, snapshot_id, bids, asks, "PU_MISMATCH")

        previous_u = snapshot_id
        for event in pending[first_index:]:
            try:
                U = int(event["U"])
                u = int(event["u"])
                pu = event.get("pu")
                pu = int(pu) if pu is not None else None
            except (KeyError, TypeError, ValueError):
                return ReplayResult(ReplayStatus.MALFORMED, previous_u, bids, asks, "INVALID_EVENT_SEQUENCE")

            if U > u:
                return ReplayResult(ReplayStatus.MALFORMED, previous_u, bids, asks, "U_GT_U")
            if u <= previous_u:
                continue
            if pu is not None and pu != previous_u:
                return ReplayResult(ReplayStatus.GAP, previous_u, bids, asks, "PU_MISMATCH")
            if pu is None and U > previous_u + 1:
                return ReplayResult(ReplayStatus.GAP, previous_u, bids, asks, "UPDATE_ID_GAP")

            try:
                self._apply(bids, event.get("b", []))
                self._apply(asks, event.get("a", []))
            except (TypeError, ValueError, KeyError):
                return ReplayResult(ReplayStatus.MALFORMED, previous_u, bids, asks, "INVALID_LEVEL_UPDATE")
            previous_u = u

        return ReplayResult(ReplayStatus.OK, previous_u, bids, asks)

    @staticmethod
    def _levels(levels: Iterable[Iterable[Any]]) -> dict[Decimal, Decimal]:
        result: dict[Decimal, Decimal] = {}
        for level in levels:
            if len(level) != 2:
                raise ValueError("level must contain price and quantity")
            price = Decimal(str(level[0]))
            qty = Decimal(str(level[1]))
            if price <= 0 or qty < 0:
                raise ValueError("invalid level")
            if qty > 0:
                result[price] = qty
        return result

    @staticmethod
    def _apply(book: dict[Decimal, Decimal], updates: Iterable[Iterable[Any]]) -> None:
        for level in updates:
            if len(level) != 2:
                raise ValueError("level must contain price and quantity")
            price = Decimal(str(level[0]))
            qty = Decimal(str(level[1]))
            if price <= 0 or qty < 0:
                raise ValueError("invalid level")
            if qty == 0:
                book.pop(price, None)
            else:
                book[price] = qty
