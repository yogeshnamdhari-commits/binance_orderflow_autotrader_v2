import pandas as pd
import pytest
from research.v9_walkforward import make_splits


def test_walkforward_splits_are_chronological_and_embargoed():
    idx = pd.date_range("2026-01-01", periods=30, freq="min", tz="UTC")
    splits = make_splits(idx, train_size=10, test_size=5, embargo=2, step=5)
    assert splits
    for train, test in splits:
        assert train.max() < test.min()
        assert test.min() - train.max() >= pd.Timedelta(minutes=3)


def test_invalid_split_parameters_rejected():
    idx = pd.date_range("2026-01-01", periods=10, freq="min", tz="UTC")
    with pytest.raises(ValueError):
        make_splits(idx, train_size=0, test_size=2, embargo=1, step=1)
