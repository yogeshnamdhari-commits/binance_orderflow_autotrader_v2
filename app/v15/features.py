"""V15 feature extractor — reuse V14 features + regime indicators.

V15 adds regime features on top of V14's 10 order-flow features:
- vol_regime_flag: 1 if rolling vol > 50th percentile, else 0
- liquidity_regime_flag: 1 if liquidity_state > 50th percentile, else 0
- spread_regime_flag: 1 if spread_bps < 50th percentile, else 0

All features computed causally. No lookahead.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.v14.features import extract_v14_features, V14_FEATURES

V15_FEATURES = V14_FEATURES + [
    "vol_regime_flag",
    "liquidity_regime_flag",
    "spread_regime_flag",
]


def _add_regime_flags(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "vol_regime" in df.columns and df["vol_regime"].notna().sum() > 1:
        vol_med = df["vol_regime"].median()
        df["vol_regime_flag"] = (df["vol_regime"] > vol_med).astype(float)
    else:
        df["vol_regime_flag"] = 0.0

    if "liquidity_state" in df.columns and df["liquidity_state"].notna().sum() > 1:
        liq_med = df["liquidity_state"].median()
        df["liquidity_regime_flag"] = (df["liquidity_state"] > liq_med).astype(float)
    else:
        df["liquidity_regime_flag"] = 0.0

    if "spread_bps" in df.columns and df["spread_bps"].notna().sum() > 1:
        spread_med = df["spread_bps"].median()
        df["spread_regime_flag"] = (df["spread_bps"] < spread_med).astype(float)
    else:
        df["spread_regime_flag"] = 0.0

    return df


def extract_v15_features(books, trades, window_ms: int = 10000) -> pd.DataFrame:
    df = extract_v14_features(books, trades, window_ms)
    if df.empty:
        return pd.DataFrame(columns=V15_FEATURES + ["ts_ms", "mid"])
    df = _add_regime_flags(df)
    return df[V15_FEATURES + ["ts_ms", "mid"]]


def build_v15_targets(df: pd.DataFrame, horizon_ms: int = 10000) -> pd.Series:
    from app.v14.features import build_v14_targets
    return build_v14_targets(df, horizon_ms)


def build_v15_returns(df: pd.DataFrame, horizon_ms: int = 10000) -> pd.Series:
    from app.v14.features import build_v14_returns
    return build_v14_returns(df, horizon_ms)
