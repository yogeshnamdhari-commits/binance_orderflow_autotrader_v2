"""Causal BTC/altcoin panel construction for V9 research."""
from __future__ import annotations
import pandas as pd


def _prepare(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "close"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    out = frame[["timestamp", "close"]].copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out = out.dropna(subset=["timestamp", "close"]).drop_duplicates("timestamp")
    return out.sort_values("timestamp").set_index("timestamp")


def build_v9_panel(btc: pd.DataFrame, followers: dict[str, pd.DataFrame], horizons=(5, 10, 15)) -> pd.DataFrame:
    if not horizons or any(int(h) <= 0 for h in horizons):
        raise ValueError("horizons must be positive")
    b = _prepare(btc).rename(columns={"close": "btc_close"})
    # BTC returns are historical/lagged information: the value at t is the
    # return ending at t, never a return containing prices after t.
    b["btc_ret_1m"] = b["btc_close"].pct_change(1)
    b["btc_ret_5m"] = b["btc_close"].pct_change(5)
    parts = []
    for symbol, frame in followers.items():
        a = _prepare(frame).rename(columns={"close": "alt_close"})
        x = b.join(a, how="inner")
        x["symbol"] = symbol
        x["alt_ret_1m"] = x["alt_close"].pct_change(1)
        for h in horizons:
            h = int(h)
            x[f"alt_return_fwd_{h}m"] = x["alt_close"].shift(-h) / x["alt_close"] - 1.0
            x[f"btc_ret_lag1_{h}m"] = x["btc_ret_1m"]
        parts.append(x.reset_index())
    if not parts:
        raise ValueError("followers cannot be empty")
    return pd.concat(parts, ignore_index=True).sort_values(["timestamp", "symbol"]).reset_index(drop=True)
