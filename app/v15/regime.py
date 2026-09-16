"""V15 regime filter — concentrate trades in high-vol, high-liquidity, tight-spread regimes.

Only trades when ALL three conditions are met:
- vol_regime > 50th percentile (high vol = larger price moves)
- liquidity_regime_flag > 0 (high liquidity = lower market impact)
- spread_regime_flag > 0 (tight spread = lower execution cost)
"""
from __future__ import annotations

import numpy as np
import pandas as pd


class V15RegimeFilter:
    def __init__(self, vol_pct: float = 50.0, liquidity_pct: float = 50.0, spread_pct: float = 50.0):
        self._vol_pct = vol_pct
        self._liquidity_pct = liquidity_pct
        self._spread_pct = spread_pct

    def fit(self, df: pd.DataFrame) -> "V15RegimeFilter":
        if "vol_regime" in df.columns and df["vol_regime"].notna().sum() > 1:
            self._vol_threshold = float(df["vol_regime"].quantile(self._vol_pct / 100.0))
        else:
            self._vol_threshold = 0.0

        if "liquidity_state" in df.columns and df["liquidity_state"].notna().sum() > 1:
            self._liquidity_threshold = float(df["liquidity_state"].quantile(self._liquidity_pct / 100.0))
        else:
            self._liquidity_threshold = 0.0

        if "spread_bps" in df.columns and df["spread_bps"].notna().sum() > 1:
            self._spread_threshold = float(df["spread_bps"].quantile(self._spread_pct / 100.0))
        else:
            self._spread_threshold = float("inf")
        return self

    def filter(self, df: pd.DataFrame) -> pd.Series:
        if not hasattr(self, "_vol_threshold"):
            self.fit(df)
        vol_ok = df.get("vol_regime", pd.Series(0, index=df.index)).fillna(0) > self._vol_threshold
        liq_ok = df.get("liquidity_state", pd.Series(0, index=df.index)).fillna(0) > self._liquidity_threshold
        spread_ok = df.get("spread_bps", pd.Series(float("inf"), index=df.index)).fillna(float("inf")) < self._spread_threshold
        return (vol_ok & liq_ok & spread_ok).astype(bool)

    def summary(self) -> dict:
        return {
            "vol_threshold": getattr(self, "_vol_threshold", None),
            "liquidity_threshold": getattr(self, "_liquidity_threshold", None),
            "spread_threshold": getattr(self, "_spread_threshold", None),
        }
