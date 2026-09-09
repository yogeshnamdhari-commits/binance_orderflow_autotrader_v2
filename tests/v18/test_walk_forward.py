import pytest

from app.v18.walk_forward import make_purged_splits


def test_splits_are_chronological_and_purged():
    splits = make_purged_splits(list(range(20)), train_size=8, test_size=4, embargo_events=2)
    assert splits[0].train == tuple(range(8))
    assert splits[0].test == tuple(range(10, 14))
    assert max(splits[0].train) < min(splits[0].test)


def test_unsorted_timestamps_are_rejected():
    with pytest.raises(ValueError, match="chronologically"):
        make_purged_splits([1, 3, 2, 4], 2, 1, 1)


def test_insufficient_data_is_rejected():
    with pytest.raises(ValueError, match="not enough events"):
        make_purged_splits(list(range(5)), 3, 2, 1)
