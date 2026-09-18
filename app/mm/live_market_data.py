from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketDataHealth:
    ready: bool
    age_ms: int
    sequence_ok: bool
    reason: str


class MarketDataGuard:
    """Validates normalized live market data before quoting."""

    def __init__(self, max_age_ms: int = 1000) -> None:
        self.max_age_ms = int(max_age_ms)
        self.last_update_id: int | None = None
        self.last_event_ts_ms: int | None = None
        self.ready = False

    def accept_depth(self, first_update_id: int, final_update_id: int, event_ts_ms: int, now_ms: int) -> MarketDataHealth:
        if final_update_id < first_update_id:
            self.ready = False
            return MarketDataHealth(False, 10**9, False, "invalid_sequence")
        if self.last_update_id is not None and first_update_id > self.last_update_id + 1:
            self.ready = False
            return MarketDataHealth(False, 10**9, False, "sequence_gap")
        if self.last_update_id is not None and final_update_id <= self.last_update_id:
            return self.health(now_ms)
        self.last_update_id = final_update_id
        self.last_event_ts_ms = int(event_ts_ms)
        self.ready = True
        return self.health(now_ms)

    def invalidate(self, reason: str) -> MarketDataHealth:
        self.ready = False
        return MarketDataHealth(False, 10**9, False, reason)

    def health(self, now_ms: int) -> MarketDataHealth:
        if not self.ready or self.last_event_ts_ms is None:
            return MarketDataHealth(False, 10**9, True, "not_ready")
        age = max(0, int(now_ms) - self.last_event_ts_ms)
        ok = age <= self.max_age_ms
        return MarketDataHealth(ok, age, True, "ok" if ok else "stale")

    def on_disconnect(self) -> MarketDataHealth:
        return self.invalidate("disconnected")
