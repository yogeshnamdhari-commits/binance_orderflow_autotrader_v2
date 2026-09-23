import pytest

from app.v19.walk_forward import make_purged_splits


def test_embargo_separates_train_and_test():
    splits = make_purged_splits(list(range(20)), 8, 4, 2)
    assert max(splits[0].train) < min(splits[0].test) - 1


def test_unsorted_timestamps_are_rejected():
    with pytest.raises(ValueError, match="chronologically"):
        make_purged_splits([2, 1, 3], 1, 1, 0)
