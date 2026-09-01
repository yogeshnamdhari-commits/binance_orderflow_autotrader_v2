"""Empirical passive-fill model primitives for V10 replay research."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class QueueState:
    initial_ahead: float
    consumed: float = 0.0

    @property
    def remaining_ahead(self) -> float:
        return max(0.0, self.initial_ahead - self.consumed)


def consume_queue(state: QueueState, executed_volume: float) -> QueueState:
    if executed_volume < 0:
        raise ValueError("executed_volume must be non-negative")
    return QueueState(state.initial_ahead, state.consumed + executed_volume)


def passive_fill_fraction(state: QueueState, own_size: float, traded_through: float) -> float:
    if own_size <= 0 or traded_through < 0:
        raise ValueError("own_size must be positive and traded_through non-negative")
    available = max(0.0, traded_through - state.remaining_ahead)
    return min(1.0, available / own_size)
