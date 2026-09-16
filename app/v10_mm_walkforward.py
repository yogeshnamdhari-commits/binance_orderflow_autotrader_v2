"""Chronological walk-forward splits for V10 execution research."""
from __future__ import annotations
import pandas as pd


def make_splits(index, train_size: int, embargo: int, test_size: int, step: int):
    idx = pd.DatetimeIndex(index)
    if len(idx) == 0 or not idx.is_monotonic_increasing or idx.has_duplicates:
        raise ValueError("index must be non-empty, strictly chronological, and duplicate-free")
    if any(int(x) <= 0 for x in (train_size, test_size, step)) or int(embargo) < 0:
        raise ValueError("train_size, test_size, step must be positive and embargo non-negative")
    train_size, embargo, test_size, step = map(int, (train_size, embargo, test_size, step))
    start = 0
    while start + train_size + embargo + test_size <= len(idx):
        train_end = start + train_size
        test_start = train_end + embargo
        test_end = test_start + test_size
        yield idx[start:train_end], idx[test_start:test_end]
        start += step
