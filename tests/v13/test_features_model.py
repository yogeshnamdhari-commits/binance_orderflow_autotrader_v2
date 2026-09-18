"""Tests for V13 features and model pipeline."""
import numpy as np
import pandas as pd
import pytest

from app.v13.config import V13Config
from app.v13.features import (
    extract_v13_features,
    build_v13_targets,
    build_v13_returns,
    V13_BASE_FEATURES,
)
from app.v13.model import V13SignalModel, V13ModelConfig


def _make_books(n=20, interval_ms=2000):
    """Synthetic BookSnapshot objects for feature testing."""
    from app.v11.parser import BookSnapshot
    books = []
    for i in range(n):
        ts = 1_700_000_000_000 + i * interval_ms
        mid = 50000.0 + i * 10.0
        bid = mid - 5
        ask = mid + 5
        books.append(BookSnapshot(
            ts_ms=ts, best_bid=bid, best_ask=ask, mid=mid,
            spread_bps=(ask - bid) / mid * 1e4,
            bids={bid: 1.0, bid - 10: 2.0}, asks={ask: 1.5, ask + 10: 3.0},
            bid_depth1=1.0, ask_depth1=1.5, bid_depth5=3.0, ask_depth5=4.5,
            bid_depth10=5.0, ask_depth10=6.5,
            qi1=0.1, qi5=0.05, qi10=0.03,
            ofi_l1=100.0, ofi_l5=200.0, ofi_l10=300.0,
            adds=50.0, cancels=30.0, net=20.0,
            buy_vol=100.0, sell_vol=50.0, tfi=0.333,
        ))
    return books


def _make_trades(n=10):
    from app.v11.parser import TradeRecord
    trades = []
    for i in range(n):
        trades.append(TradeRecord(
            ts_ms=1_700_000_000_000 + i * 200, price=50010.0,
            qty=0.1, aggressor_side="BUY", buyer_is_maker=False,
        ))
    return trades


def test_features_contain_v13_specific_columns():
    books = _make_books()
    trades = _make_trades()
    df = extract_v13_features(books, trades, window_ms=2000)
    for f in V13_BASE_FEATURES:
        assert f in df.columns, f"missing feature: {f}"
    assert "trade_intensity" in df.columns
    assert "ofi_persistence" in df.columns
    assert "signed_vol_imbalance" in df.columns


def test_target_horizon_is_2_seconds():
    books = _make_books(n=50, interval_ms=2000)
    trades = _make_trades()
    df = extract_v13_features(books, trades, window_ms=2000)
    targets = build_v13_targets(df, horizon_ms=2000)
    assert len(targets) == len(df)


def test_v13_model_trains_and_freezes(tmp_path):
    rng = np.random.RandomState(42)
    n = 400
    X = pd.DataFrame({f: rng.randn(n) for f in V13_BASE_FEATURES})
    y = pd.Series((X["ofi_l1"] + 0.5 * X["tfi_2000"] > 0).astype(int).values)
    returns = pd.Series(y * 5.0 - (1 - y) * 5.0, dtype=float)

    model = V13SignalModel()
    metrics = model.fit(X, y, returns=returns)
    assert metrics["val_auc"] > 0.55  # synthetic signal is learnable

    path = tmp_path / "v13_model.joblib"
    checksum = model.save(path)
    assert path.exists()

    loaded = V13SignalModel.load(path)
    assert loaded.is_fitted
    assert loaded._feature_names == model._feature_names
    assert loaded.val_auc == pytest.approx(model.val_auc)

    # determinism: same checksum
    path2 = tmp_path / "v13_model2.joblib"
    model.save(path2)
    assert checksum == model.save(path)
