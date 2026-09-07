"""V11 feature extractor — computes V5 feature set from parsed book/trade data.

Features are computed causally (only using data available at each event time).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


# V5_FEATURES exact set (must match app/features.py V5_FEATURES)
V11_FEATURES = [
    "ofi_l1", "ofi_norm_l1", "qi_l1", "di_l5", "di_l10",
    "mpd_bps", "spread_bps", "bid_cancel_bps", "ask_add_bps",
    "cancel_pressure", "tfi_500", "liq_depletion",
    "log_depth1", "log_depth5", "log_event_rate",
    "depth_slope_bps", "vol_500",
]


@dataclass
class FeatureWindow:
    books: list[Any]
    trades: list[Any]
    window_ms: int = 1000


def _multi_di(bids: dict[float, float], asks: dict[float, float], n: int = 5) -> float:
    """Distance-weighted multi-level depth imbalance."""
    top_b = sorted(bids.items(), reverse=True)[:n]
    top_a = sorted(asks.items())[:n]
    wb = sum((n - i + 1) * q for i, (_, q) in enumerate(top_b[:n]))
    wa = sum((n - i + 1) * q for i, (_, q) in enumerate(top_a[:n]))
    return (wb - wa) / (wb + wa) if (wb + wa) else 0.0


def _depth_slope_bps(bids: dict[float, float], asks: dict[float, float], mid: float) -> float:
    """Log-depth decay slope."""
    if mid is None or mid <= 0:
        return 0.0
    bq = [q for _, q in sorted(bids.items(), reverse=True)[:10]]
    aq = [q for _, q in sorted(asks.items())[:10]]
    if not bq and not aq:
        return 0.0
    logq = np.log1p(np.array(bq + aq, dtype=float))
    if len(logq) < 2:
        return 0.0
    x = np.arange(len(logq), dtype=float)
    coeffs = np.polyfit(x, logq, 1)
    return float(coeffs[0])


def _trailing_vol(mids: list[float | None], window: int = 500) -> float:
    """Realized volatility over trailing window (bps)."""
    valid = [m for m in mids if m is not None and m > 0]
    if len(valid) < 3:
        return 0.0
    seg = valid[-window:]
    if len(seg) < 2:
        return 0.0
    rets = np.diff(np.log(seg))
    return float(np.sqrt(np.sum(rets ** 2)) * 1e4)


def extract_v11_features(books: list[Any], trades: list[Any], window_ms: int = 1000) -> pd.DataFrame:
    """Extract V5 feature set from parsed book snapshots and trades.

    Args:
        books: List of BookSnapshot objects (chronological)
        trades: List of TradeRecord objects (chronological)
        window_ms: Feature window in milliseconds

    Returns:
        DataFrame with V11_FEATURES columns, indexed by ts_ms
    """
    if not books:
        return pd.DataFrame(columns=V11_FEATURES + ["ts_ms", "mid"])

    rows = []
    trade_idx = 0
    n_trades = len(trades)
    mids_hist: list[float | None] = []

    for bk in books:
        # advance trade index
        while trade_idx < n_trades and trades[trade_idx].ts_ms <= bk.ts_ms:
            trade_idx += 1

        # window trades
        window_start = bk.ts_ms - window_ms
        w_trades = [t for t in trades[:trade_idx] if t.ts_ms >= window_start]
        w_buy = sum(t.qty for t in w_trades if t.aggressor_side == "BUY")
        w_sell = sum(t.qty for t in w_trades if t.aggressor_side == "SELL")
        w_tot = w_buy + w_sell
        tfi = (w_buy - w_sell) / w_tot if w_tot else 0.0

        # depth sums
        d1 = bk.bid_depth1 + bk.ask_depth1
        d5 = bk.bid_depth5 + bk.ask_depth5
        d10 = bk.bid_depth10 + bk.ask_depth10

        # ofi_norm_l1
        ofi_norm_l1 = bk.ofi_l1 / d1 if d1 else 0.0

        # microprice and mpd_bps
        microb = None
        if bk.best_bid is not None and bk.best_ask is not None:
            qb = bk.bids.get(bk.best_bid, 0.0)
            qa = bk.asks.get(bk.best_ask, 0.0)
            tot = qb + qa
            if tot > 0:
                microb = (bk.best_ask * qb + bk.best_bid * qa) / tot
        mpd_bps = 0.0
        if bk.mid and microb:
            mpd_bps = ((microb - bk.mid) / bk.mid * 1e4)

        # cancel_pressure
        cancel_pressure = (bk.cancels) / (d1 + 1e-9)

        # liq_depletion: use trade volume vs depth
        liq_depletion = w_tot / (d5 + 1e-9) if d5 else 0.0

        # log depths
        log_depth1 = np.log1p(d1)
        log_depth5 = np.log1p(d5)

        # log_event_rate
        log_event_rate = np.log1p(len(w_trades))

        # depth_slope
        depth_slope_bps = _depth_slope_bps(bk.bids, bk.asks, bk.mid)

        # vol_500
        mids_hist.append(bk.mid)
        vol_500 = _trailing_vol(mids_hist, window=500)

        # bid_cancel_bps and ask_add_bps (use total cancels/adds normalized by mid)
        to_bps = lambda q: q / bk.mid * 1e4 if bk.mid else 0.0
        bid_cancel_bps = to_bps(bk.cancels * 0.5)  # split cancels evenly (approximation)
        ask_add_bps = to_bps(bk.adds * 0.5)

        rows.append({
            "ts_ms": bk.ts_ms,
            "ofi_l1": bk.ofi_l1,
            "ofi_norm_l1": ofi_norm_l1,
            "qi_l1": bk.qi1,
            "di_l5": _multi_di(bk.bids, bk.asks, 5),
            "di_l10": _multi_di(bk.bids, bk.asks, 10),
            "mpd_bps": mpd_bps,
            "spread_bps": bk.spread_bps if bk.spread_bps is not None else 0.0,
            "bid_cancel_bps": bid_cancel_bps,
            "ask_add_bps": ask_add_bps,
            "cancel_pressure": cancel_pressure,
            "tfi_500": tfi,
            "liq_depletion": liq_depletion,
            "log_depth1": log_depth1,
            "log_depth5": log_depth5,
            "log_event_rate": log_event_rate,
            "depth_slope_bps": depth_slope_bps,
            "vol_500": vol_500,
            "mid": bk.mid if bk.mid is not None else 0.0,
        })

    df = pd.DataFrame(rows)
    # forward-fill any NaN from spread_bps
    df["spread_bps"] = df["spread_bps"].fillna(0.0)
    return df


def build_targets(df: pd.DataFrame, horizon_ms: int = 500) -> pd.Series:
    """Build binary classification target: did mid-price rise in next horizon_ms?

    Args:
        df: Feature DataFrame with 'ts_ms' and 'mid' columns
        horizon_ms: Forward horizon in milliseconds

    Returns:
        Binary Series (1 = price rose, 0 = price fell or unchanged)
    """
    if len(df) < 2:
        return pd.Series(dtype=int)

    mids = df["mid"].values
    ts = df["ts_ms"].values
    target = np.zeros(len(df), dtype=int)

    for i in range(len(df) - 1):
        t_target = ts[i] + horizon_ms
        # find first future mid at or after horizon
        j = i + 1
        while j < len(df) and ts[j] < t_target:
            j += 1
        if j >= len(df):
            break
        if mids[j] > mids[i]:
            target[i] = 1
        elif mids[j] < mids[i]:
            target[i] = 0
        else:
            target[i] = 0  # treat no-change as negative

    return pd.Series(target, index=df.index)


def build_regression_target(df: pd.DataFrame, horizon_ms: int = 500) -> pd.Series:
    """Build regression target: forward return in bps."""
    if len(df) < 2:
        return pd.Series(dtype=float)

    mids = df["mid"].values
    ts = df["ts_ms"].values
    ret = np.full(len(df), np.nan)

    for i in range(len(df) - 1):
        t_target = ts[i] + horizon_ms
        j = i + 1
        while j < len(df) and ts[j] < t_target:
            j += 1
        if j >= len(df):
            break
        if mids[i] > 0 and mids[j] > 0:
            ret[i] = (mids[j] - mids[i]) / mids[i] * 1e4
        else:
            ret[i] = 0.0

    return pd.Series(ret, index=df.index)
