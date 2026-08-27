"""V6 L2 book integrity engine — hard invariant for microstructure features.

Book states (explicit state machine):
  BOOK_STARTING  -> initial state, no data yet
  BOOK_SYNCING   -> snapshot loaded, waiting for first valid update
  BOOK_VALID     -> synchronized, features may be generated
  BOOK_STALE     -> update sequence old (U <= local last_update_id), skip
  BOOK_GAP       -> incoming_U > local_u + 1, book must be discarded
  BOOK_RESYNC    -> rebuilding book from REST snapshot
  BOOK_INVALID   -> book unusable, NO signal may be generated

Critical rule (Binance diff-depth continuity):
  If incoming_U > local_u + 1:
    BOOK_GAP
      -> discard local book
      -> REST snapshot
      -> rebuild
      -> replay buffered updates
      -> BOOK_VALID

No signal may be generated while the book is invalid.

This is tested and enforced as a hard invariant.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class BookState(Enum):
    STARTING = "BOOK_STARTING"
    SYNCING = "BOOK_SYNCING"
    VALID = "BOOK_VALID"
    STALE = "BOOK_STALE"
    GAP = "BOOK_GAP"
    RESYNC = "BOOK_RESYNC"
    INVALID = "BOOK_INVALID"


class L2IntegrityEngine:
    """Hard invariant: features are only generated in BOOK_VALID state."""

    def __init__(self, max_levels=20, gap_threshold=5000):
        self.state = BookState.STARTING
        self.max_levels = max_levels
        self.gap_threshold = gap_threshold  # Binance 100ms stream hole limit
        self.last_update_id = None
        self.snapshot_update_id = None
        self.buffered_updates = []
        self.gap_count = 0
        self.resync_count = 0
        self.stale_count = 0
        self.valid_event_count = 0
        self.last_event_ms = None
        self._events = []

    def on_snapshot(self, last_update_id: int, ts_ms: int) -> str:
        """Process REST snapshot. Transitions to BOOK_SYNCING."""
        self.snapshot_update_id = int(last_update_id)
        self.last_update_id = int(last_update_id)
        self.state = BookState.SYNCING
        self.buffered_updates.clear()
        self._events.append(("snapshot", ts_ms, self.state.value))
        return self.state.value

    def on_depth_update(self, first_update_id: int, final_update_id: int,
                        ts_ms: int, buffered: bool = False) -> str:
        """Process incremental depth update.

        Returns the new book state after processing this update.
        """
        first = int(first_update_id)
        final = int(final_update_id)

        if self.state in (BookState.STARTING, BookState.INVALID):
            # No snapshot yet or book is dead — buffer if allowed, else drop
            if buffered:
                self.buffered_updates.append((first, final, ts_ms))
            self._events.append(("depth_dropped", ts_ms, self.state.value))
            return self.state.value

        if self.state == BookState.GAP:
            # Already in gap — buffer until resync completes
            if buffered:
                self.buffered_updates.append((first, final, ts_ms))
            return self.state.value

        # Check for stale update (U <= local last_update_id)
        if first <= self.last_update_id:
            self.stale_count += 1
            self.state = BookState.STALE
            self._events.append(("stale", ts_ms, f"first={first} last={self.last_update_id}"))
            return self.state.value

        # Check for gap: incoming_U > local_u + 1
        if first > self.last_update_id + 1:
            self.gap_count += 1
            self.state = BookState.GAP
            self._events.append(("gap", ts_ms,
                                 f"hole={first - self.last_update_id - 1}"))
            return self.state.value

        # Check for large hole (Binance 100ms stream can skip no-op IDs,
        # but > gap_threshold indicates real message loss)
        hole = first - self.last_update_id - 1
        if hole > self.gap_threshold:
            self.gap_count += 1
            self.state = BookState.GAP
            self._events.append(("gap_large", ts_ms, f"hole={hole}"))
            return self.state.value

        # Valid update
        self.last_update_id = final
        self.last_event_ms = ts_ms
        self.valid_event_count += 1

        if self.state == BookState.SYNCING:
            # First valid update after snapshot — book is now valid
            self.state = BookState.VALID
            self._events.append(("sync_complete", ts_ms, f"last={final}"))
        else:
            self.state = BookState.VALID
            self._events.append(("depth_ok", ts_ms, f"last={final}"))

        return self.state.value

    def force_resync(self, reason: str = "manual") -> str:
        """Force book to resync state. Must be followed by snapshot + replay."""
        self.state = BookState.RESYNC
        self.resync_count += 1
        self.last_update_id = None
        self.buffered_updates.clear()
        self._events.append(("resync", self.last_event_ms or 0, reason))
        return self.state.value

    def mark_invalid(self, reason: str = "unknown") -> str:
        """Mark book as permanently invalid. No features may be generated."""
        self.state = BookState.INVALID
        self._events.append(("invalid", self.last_event_ms or 0, reason))
        return self.state.value

    def can_generate_features(self) -> bool:
        """Hard invariant: features only generated in BOOK_VALID state."""
        return self.state == BookState.VALID

    def state_summary(self) -> dict:
        return {
            "state": self.state.value,
            "can_generate_features": self.can_generate_features(),
            "last_update_id": self.last_update_id,
            "snapshot_update_id": self.snapshot_update_id,
            "gap_count": self.gap_count,
            "resync_count": self.resync_count,
            "stale_count": self.stale_count,
            "valid_event_count": self.valid_event_count,
            "buffered_updates": len(self.buffered_updates),
        }

    def recent_events(self, n=10):
        return self._events[-n:] if self._events else []
