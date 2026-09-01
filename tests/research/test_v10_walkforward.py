import pandas as pd
from app.v10_mm_walkforward import make_splits


def test_walkforward_has_train_then_embargo_then_oos():
    idx = pd.date_range("2026-01-01", periods=20, freq="min", tz="UTC")
    splits = list(make_splits(idx, train_size=8, embargo=2, test_size=4, step=4))
    assert len(splits) == 3
    train, test = splits[0]
    assert train[-1] < test[0]
    assert (test[0] - train[-1]).total_seconds() >= 3 * 60


def test_walkforward_rejects_unsorted_index():
    idx = pd.DatetimeIndex(["2026-01-01 00:02Z", "2026-01-01 00:01Z"])
    try:
        list(make_splits(idx, train_size=1, embargo=0, test_size=1, step=1))
    except ValueError:
        return
    assert False
