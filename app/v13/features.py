"""V13 feature extractor — order-flow persistence features at 2s horizon.

Reuses the V11 causal feature extractor (tested, no leakage) at window_ms=2000
and adds three V13-specific features motivated by order-flow persistence
literature:

  - signed_vol_imbalance: normalized aggressive trade imbalance (robust to
    volume scale).
  - ofi_persistence: consistency of recent OFI sign over the trailing window
    (Cont & de Prado 2016 — persistent flow signals continuation).
  - trade_intensity: trade events per second (market-state regime proxy).
  - price_momentum: recent mid return over the feature window (for context).

All features are computed causally from book snapshots (causal state) and
trade records (causal, timestamp-ordered). No future data is used.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from app.v11.features import extract_v11_features, build_targets, build_regression_target

V13_BASE_FEATURES = [
    "ofi_l1",
    "ofi_norm_l1",
    "qi_l1",
    "di_l5",
    "di_l10",
    "mpd_bps",
    "spread_bps",
    "bid_cancel_bps",
    "ask_add_bps",
    "cancel_pressure",
    "tfi_2000",
    "liq_depletion",
    "log_depth1",
    "log_depth5",
    "log_event_rate",
    "depth_slope_bps",
    "vol_2000",
    "trade_intensity",
    "ofi_persistence",
    "price_momentum_2000",
    "signed_vol_imbalance",
]


def extract_v13_features(books: list, trades: list, window_ms: int = 2000) -> pd.DataFrame:
    """Extract V13 feature set from parsed book snapshots and trades.

    Args:
        books: List of BookSnapshot objects (chronological).
        trades: List of TradeRecord objects (chronological).
        window_ms: Feature window in milliseconds (default 2000).

    Returns:
        DataFrame with V13_BASE_FEATURES + ts_ms/mid columns, indexed by row.
    """
    if not books:
        return pd.DataFrame(columns=V13_BASE_FEATURES + ["ts_ms", "mid"])

    base = extract_v11_features(books, trades, window_ms=window_ms)
    if base.empty:
        return base

    # Rename window-dependent V11 columns to V13 naming
    rename_map = {}
    if "tfi_500" in base.columns:
        rename_map["tfi_500"] = "tfi_2000"
    if "vol_500" in base.columns:
        rename_map["vol_500"] = "vol_2000"
    base = base.rename(columns=rename_map)

    # --- V13 new features ---
    window_s = window_ms / 1000.0
    ts = base["ts_ms"].values
    log_event_rate = base["log_event_rate"].values
    trade_intensity = np.expm1(log_event_rate) / window_s  # events per second

    # signed_vol_imbalance: (buy - sell) / max(buy, sell) — robust normalization
    # Reconstruct buy/sell volume from tfi and log_event_rate is not possible,
    # so compute from raw trade data per snapshot window.
    n_books = len(base)
    signed_vol_imbalance = np.zeros(n_books)
    ofi_persistence = np.zeros(n_books)
    price_momentum = np.zeros(n_books)

    mids = base["mid"].values
    ofi = base["ofi_l1"].values
    trade_idx = 0
    n_trades = len(trades)

    for i, bk in enumerate(books):
        # advance trades to current snapshot time
        while trade_idx < n_trades and trades[trade_idx].ts_ms <= bk.ts_ms:
            trade_idx += 1

        window_start = bk.ts_ms - window_ms
        w_trades = [t for t in trades[:trade_idx] if t.ts_ms >= window_start]
        if w_trades:
            w_buy = sum(t.qty for t in w_trades if t.aggressor_side == "BUY")
            w_sell = sum(t.qty for t in w_trades if t.aggressor_side == "SELL")
            denom = max(w_buy, w_sell, 1e-9)
            signed_vol_imbalance[i] = (w_buy - w_sell) / denom

        # ofi_persistence: fraction of positive OFI in trailing window
        lookback = max(1, int(window_ms / 200))  # ~5 observations per second at 200ms cadence
        start = max(0, i - lookback)
        recent_ofi = ofi[start:i + 1]
        if len(recent_ofi) > 0:
            ofi_persistence[i] = np.mean(recent_ofi > 0)

        # price_momentum: return over the window
        if i >= 1 and mids[i] > 0:
            prev_idx = max(0, start)
            if mids[prev_idx] > 0:
                price_momentum[i] = (mids[i] - mids[prev_idx]) / mids[prev_idx] * 1e4

    base["trade_intensity"] = trade_intensity
    base["ofi_persistence"] = ofi_persistence
    base["price_momentum_2000"] = price_momentum
    base["signed_vol_imbalance"] = signed_vol_imbalance

    feature_cols = [c for c in V13_BASE_FEATURES if c in base.columns]
    result = base[feature_cols + ["ts_ms", "mid"]].copy()
    result = result.replace([np.inf, -np.inf], 0.0)
    return result


def build_v13_targets(df: pd.DataFrame, horizon_ms: int = 2000) -> pd.Series:
    """Binary target: did mid-price rise within horizon_ms?"""
    return build_targets(df, horizon_ms=horizon_ms)


def build_v13_returns(df: pd.DataFrame, horizon_ms: int = 2000) -> pd.Series:
    """Regression target: forward return in bps over horizon_ms."""
    return build_regression_target(df, horizon_ms=horizon_ms)
