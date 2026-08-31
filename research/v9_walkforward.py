"""Chronological walk-forward split construction for V9."""
from __future__ import annotations
import pandas as pd


def make_splits(index, train_size: int, test_size: int, embargo: int = 0, step: int | None = None):
    if train_size <= 0 or test_size <= 0 or embargo < 0:
        raise ValueError("train_size and test_size must be positive; embargo must be non-negative")
    step = test_size if step is None else step
    if step <= 0:
        raise ValueError("step must be positive")
    idx = pd.DatetimeIndex(index).sort_values().unique()
    if len(idx) < train_size + embargo + test_size:
        return []
    splits = []
    start = 0
    while start + train_size + embargo + test_size <= len(idx):
        train = idx[start:start + train_size]
        test_start = start + train_size + embargo
        test = idx[test_start:test_start + test_size]
        splits.append((train, test))
        start += step
    return splits
