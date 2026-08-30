import pandas as pd
from app.v9_features import build_v9_panel


def _frame(symbol, prices):
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=len(prices), freq="min", tz="UTC"),
        "symbol": symbol,
        "close": prices,
    })


def test_forward_labels_use_only_strictly_future_price():
    btc = _frame("BTCUSDT", [100, 101, 102, 103, 104, 105])
    alt = _frame("ALTUSDT", [10, 10, 10, 11, 12, 13])
    panel = build_v9_panel(btc, {"ALTUSDT": alt}, horizons=(1,))
    row = panel.loc[panel["timestamp"] == pd.Timestamp("2026-01-01 00:02", tz="UTC")].iloc[0]
    assert row["alt_return_fwd_1m"] == 0.10


def test_predictors_are_lagged_and_no_future_btc_return_is_used():
    btc = _frame("BTCUSDT", [100, 110, 120, 130])
    alt = _frame("ALTUSDT", [10, 10, 10, 10])
    panel = build_v9_panel(btc, {"ALTUSDT": alt}, horizons=(1,))
    row = panel.iloc[2]
    assert row["btc_ret_1m"] == 110 / 100 - 1
    assert row["btc_ret_1m"] != 130 / 120 - 1
