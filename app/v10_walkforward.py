"""Chronological walk-forward split utilities for V10 OOS research."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Tuple, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Fold:
    train: Tuple[T, ...]
    test: Tuple[T, ...]


def chronological_folds(
    observations: Sequence[T], *, train_size: int, test_size: int, step: int
) -> Tuple[Fold, ...]:
    """Create rolling, chronological train/test folds with no look-ahead."""
    if train_size <= 0 or test_size <= 0 or step <= 0:
        raise ValueError("train_size, test_size and step must be positive")
    if len(observations) < train_size + test_size:
        return ()

    folds = []
    start = 0
    while start + train_size + test_size <= len(observations):
        train_end = start + train_size
        test_end = train_end + test_size
        folds.append(
            Fold(
                train=tuple(observations[start:train_end]),
                test=tuple(observations[train_end:test_end]),
            )
        )
        start += step
    return tuple(folds)
