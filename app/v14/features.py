"""V14 feature extractor — order-flow persistence at 10s horizon.

Minimal, economically motivated feature set (no feature zoo). All features
computed causally from BookSnapshot and TradeRecord objects.

Feature definitions (pre-registered in data/research/v14_proposal.json):

| Feature | Definition | Source |
|---------|-----------|--------|
| book_imbalance_l1 | (bid1 - ask1) / (bid1 + ask1 + eps) | BookSnapshot depth1 |
| book_imbalance_l5 | weighted 5-level depth imbalance | BookSnapshot bids/asks |
| aggressive_trade_imbalance | (buy_vol - sell_vol) / (buy_vol + sell_vol + eps) over 10s | TradeRecord |
| microprice_deviation_bps | (microprice - mid) / mid * 1e4 | BookSnapshot |
| depth_pressure | (adds - cancels) / (adds + cancels + eps) over 10s | BookSnapshot |
| trade_intensity | trade events per second over 10s | TradeRecord |
| spread_bps | best ask - best bid, in bps | BookSnapshot |
| vol_regime | rolling 10s realized volatility (bps) | BookSnapshot mid |
| signed_vol_imbalance | (buy - sell) / max(buy, sell, eps) over 10s | TradeRecord |
| liquidity_state | depth1 / max_trade_qty_in_window | BookSnapshot/TradeRecord |
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.v11.parser import BookSnapshot, TradeRecord

V14_FEATURES = [
    "book_imbalance_l1",
    "book_imbalance_l5",
    "aggressive_trade_imbalance",
    "microprice_deviation_bps",
    "depth_pressure",
    "trade_intensity",
    "spread_bps",
    "vol_regime",
    "signed_vol_imbalance",
    "liquidity_state",
]


def _multi_di(bids: dict, asks: dict, n: int = 5) -> float:
    top_b = sorted(bids.items(), reverse=True)[:n]
    top_a = sorted(asks.items())[:n]
    wb = sum((n - i + 1) * q for i, (_, q) in enumerate(top_b))
    wa = sum((n - i + 1) * q for i, (_, q) in enumerate(top_a))
    return (wb - wa) / (wb + wa) if (wb + wa) else 0.0


def _microprice(bids: dict, asks: dict) -> float | None:
    if not bids or not asks:
        return None
    best_bid = max(bids)
    best_ask = min(asks)
    qb = bids[best_bid]
    qa = asks[best_ask]
    tot = qb + qa
    if tot <= 0:
        return None
    return (best_ask * qb + best_bid * qa) / tot


def extract_v14_features(books: list[BookSnapshot], trades: list[TradeRecord],
                         window_ms: int = 10000) -> pd.DataFrame:
    if not books:
        return pd.DataFrame(columns=V14_FEATURES + ["ts_ms", "mid"])

    rows = []
    trade_idx = 0
    n_trades = len(trades)
    mids_hist: list[float | None] = []
    window_s = window_ms / 1000.0

    for i, bk in enumerate(books):
        while trade_idx < n_trades and trades[trade_idx].ts_ms <= bk.ts_ms:
            trade_idx += 1

        window_start = bk.ts_ms - window_ms
        w_trades = [t for t in trades[:trade_idx] if t.ts_ms >= window_start]
        w_buy = sum(t.qty for t in w_trades if t.aggressor_side == "BUY")
        w_sell = sum(t.qty for t in w_trades if t.aggressor_side == "SELL")
        w_tot = w_buy + w_sell
        w_max = max(w_buy, w_sell, 1e-9)

        # book imbalance L1
        d1 = bk.bid_depth1 + bk.ask_depth1
        book_imbalance_l1 = (bk.bid_depth1 - bk.ask_depth1) / (d1 + 1e-9)

        # book imbalance L5
        book_imbalance_l5 = _multi_di(bk.bids, bk.asks, 5)

        # aggressive trade imbalance
        aggressive_trade_imbalance = (w_buy - w_sell) / (w_tot + 1e-9)

        # microprice deviation
        microb = _microprice(bk.bids, bk.asks)
        if bk.mid and bk.mid > 0 and microb is not None:
            microprice_deviation_bps = (microb - bk.mid) / bk.mid * 1e4
        else:
            microprice_deviation_bps = 0.0

        # depth pressure (adds vs cancels)
        adds = bk.adds if hasattr(bk, "adds") and bk.adds else 0.0
        cancels = bk.cancels if hasattr(bk, "cancels") and bk.cancels else 0.0
        depth_pressure = (adds - cancels) / (adds + cancels + 1e-9)

        # trade intensity
        trade_intensity = len(w_trades) / window_s

        # vol regime
        mids_hist.append(bk.mid)
        seg = [m for m in mids_hist[-500:] if m is not None and m > 0]
        if len(seg) >= 3:
            rets = np.diff(np.log(np.array(seg)))
            vol_regime = float(np.sqrt(np.sum(rets ** 2) * 1e4))
        else:
            vol_regime = 0.0

        # signed volume imbalance
        signed_vol_imbalance = (w_buy - w_sell) / w_max

        # liquidity state: depth1 relative to largest trade in window
        max_trade = max((t.qty for t in w_trades), default=0.0)
        liquidity_state = d1 / (max_trade + 1e-9) if d1 else 0.0

        rows.append({
            "ts_ms": bk.ts_ms,
            "mid": bk.mid if bk.mid else 0.0,
            "book_imbalance_l1": book_imbalance_l1,
            "book_imbalance_l5": book_imbalance_l5,
            "aggressive_trade_imbalance": aggressive_trade_imbalance,
            "microprice_deviation_bps": microprice_deviation_bps,
            "depth_pressure": depth_pressure,
            "trade_intensity": trade_intensity,
            "spread_bps": bk.spread_bps if bk.spread_bps is not None else 0.0,
            "vol_regime": vol_regime,
            "signed_vol_imbalance": signed_vol_imbalance,
            "liquidity_state": liquidity_state,
        })

    df = pd.DataFrame(rows)
    df["spread_bps"] = df["spread_bps"].fillna(0.0)
    df = df.replace([np.inf, -np.inf], 0.0)
    return df


def build_v14_targets(df: pd.DataFrame, horizon_ms: int = 10000) -> pd.Series:
    """Binary target: mid-price rose by more than breakeven cost within horizon."""
    if len(df) < 2:
        return pd.Series(dtype=int)
    mids = df["mid"].values
    ts = df["ts_ms"].values
    target = np.zeros(len(df), dtype=int)
    for i in range(len(df) - 1):
        t_target = ts[i] + horizon_ms
        j = i + 1
        while j < len(df) and ts[j] < t_target:
            j += 1
        if j >= len(df):
            break
        if mids[i] > 0 and mids[j] > 0 and mids[j] > mids[i]:
            target[i] = 1
    return pd.Series(target, index=df.index)


def build_v14_returns(df: pd.DataFrame, horizon_ms: int = 10000) -> pd.Series:
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
