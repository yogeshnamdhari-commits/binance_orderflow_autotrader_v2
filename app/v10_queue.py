"""Conservative observable queue-ahead state for V10 research replay."""
from __future__ import annotations


class QueueEstimator:
    """Track only observable depletion; never assume replenishment improves rank."""

    def __init__(self) -> None:
        self._ahead: dict[str, float] = {}

    def initial_ahead(self, side: str, displayed_size: float) -> float:
        value = self._validate_size(displayed_size)
        self._ahead[side] = value
        return value

    def start(self, side: str, displayed_size: float) -> float:
        return self.initial_ahead(side, displayed_size)

    def apply_execution(self, side: str, executed_size: float) -> float:
        value = self._validate_size(executed_size)
        current = self._ahead.get(side, 0.0)
        self._ahead[side] = max(0.0, current - value)
        return self._ahead[side]

    def apply_cancel(self, side: str, cancelled_ahead_size: float) -> float:
        value = self._validate_size(cancelled_ahead_size)
        current = self._ahead.get(side, 0.0)
        self._ahead[side] = max(0.0, current - value)
        return self._ahead[side]

    def apply_replenishment(self, side: str, replenished_size: float) -> float:
        """Record replenishment separately; conservatively leave queue-ahead unchanged."""
        self._validate_size(replenished_size)
        return self._ahead.get(side, 0.0)

    def ahead(self, side: str) -> float:
        return self._ahead.get(side, 0.0)

    @staticmethod
    def _validate_size(value: float) -> float:
        value = float(value)
        if value < 0:
            raise ValueError("queue size cannot be negative")
        return value
