from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class Split:
    train: tuple[int, ...]
    test: tuple[int, ...]


def make_purged_splits(
    timestamps_ns: Sequence[int],
    train_size: int,
    test_size: int,
    embargo_events: int,
) -> list[Split]:
    """Create expanding chronological splits with a purge/embargo gap."""
    if train_size <= 0 or test_size <= 0 or embargo_events < 0:
        raise ValueError("split sizes must be positive and embargo must be non-negative")
    if any(timestamps_ns[i] > timestamps_ns[i + 1] for i in range(len(timestamps_ns) - 1)):
        raise ValueError("timestamps must be sorted chronologically")

    splits: list[Split] = []
    start = 0
    n = len(timestamps_ns)
    while start + train_size + embargo_events + test_size <= n:
        train_end = start + train_size
        test_start = train_end + embargo_events
        test_end = test_start + test_size
        splits.append(Split(tuple(range(start, train_end)), tuple(range(test_start, test_end))))
        start = test_start
    if not splits:
        raise ValueError("not enough events for one purged split")
    return splits
