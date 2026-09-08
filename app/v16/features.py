"""V16 event-time feature extractor.

Features are computed at each order-book event timestamp using only
past/present data. No fixed bars — event-driven.

Feature families:
A. OFI (order-flow imbalance)
B. Trade flow
C. Queue/book state
D. Dynamics (changes, persistence)
E. Regime
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.v14.features import extract_v14_features, V14_FEATURES

V16_FEATURES = V14_FEATURES + [
    "ofi_l1_best",
    "ofi_l1_normalized",
    "ofi_l1_depth_normalized",
    "signed_trade_imbalance",
    "aggressive_buy_vol",
    "aggressive_sell_vol",
    "burstiness",
    "volume_imbalance",
    "bid_queue_imbalance",
    "ask_queue_imbalance",
    "multi_level_depth_imbalance",
    "depth_slope",
    "microprice_displacement",
    "book_pressure",
    "ofi_change",
    "queue_imbalance_change",
    "persistence",
    "event_intensity",
    "short_term_volatility",
    "spread_regime_flag",
    "volatility_regime_flag",
    "liquidity_regime_flag",
    "activity_regime_flag",
]


def _compute_ofi(books: list, trades: list, window_ms: int = 10000) -> pd.DataFrame:
    """Compute OFI at each book event."""
    rows = []
    trade_idx = 0
    n_trades = len(trades)
    prev_best_bid_qty = 0.0
    prev_best_ask_qty = 0.0
    prev_mid = None

    for i, bk in enumerate(books):
        while trade_idx < n_trades and trades[trade_idx].ts_ms <= bk.ts_ms:
            trade_idx += 1

        window_start = bk.ts_ms - window_ms
        w_trades = [t for t in trades[:trade_idx] if t.ts_ms >= window_start]

        best_bid_qty = bk.bid_depth1
        best_ask_qty = bk.ask_depth1
        mid = bk.mid if bk.mid else 0.0

        if prev_mid is not None and prev_mid > 0 and mid > 0:
            ofi_l1 = (best_bid_qty - prev_best_bid_qty) - (best_ask_qty - prev_best_ask_qty)
            ofi_normalized = ofi_l1 / (best_bid_qty + best_ask_qty + 1e-9)
            depth = best_bid_qty + best_ask_qty
            ofi_depth_normalized = ofi_l1 / (depth + 1e-9)
            ofi_change = ofi_l1 - (ofi_l1 if i == 0 else rows[-1].get("ofi_l1_best", 0))
        else:
            ofi_l1 = 0.0
            ofi_normalized = 0.0
            ofi_depth_normalized = 0.0
            ofi_change = 0.0

        prev_best_bid_qty = best_bid_qty
        prev_best_ask_qty = best_ask_qty
        prev_mid = mid

        buy_vol = sum(t.qty for t in w_trades if t.aggressor_side == "BUY")
        sell_vol = sum(t.qty for t in w_trades if t.aggressor_side == "SELL")
        tot_vol = buy_vol + sell_vol
        trade_count = len(w_trades)

        rows.append({
            "ts_ms": bk.ts_ms,
            "mid": mid,
            "ofi_l1_best": ofi_l1,
            "ofi_l1_normalized": ofi_normalized,
            "ofi_l1_depth_normalized": ofi_depth_normalized,
            "ofi_change": ofi_change,
            "signed_trade_imbalance": (buy_vol - sell_vol) / (tot_vol + 1e-9),
            "aggressive_buy_vol": buy_vol,
            "aggressive_sell_vol": sell_vol,
            "trade_intensity": trade_count / (window_ms / 1000.0),
            "burstiness": float(np.std([t.qty for t in w_trades])) if w_trades else 0.0,
            "volume_imbalance": (buy_vol - sell_vol) / (max(buy_vol, sell_vol, 1e-9)),
        })

    return pd.DataFrame(rows)


def _compute_queue_book_features(books: list, trades: list, window_ms: int = 10000) -> pd.DataFrame:
    """Compute queue/book-state features at each book event."""
    rows = []
    trade_idx = 0
    n_trades = len(trades)
    prev_bid_imb = 0.0
    prev_ask_imb = 0.0

    for i, bk in enumerate(books):
        while trade_idx < n_trades and trades[trade_idx].ts_ms <= bk.ts_ms:
            trade_idx += 1

        window_start = bk.ts_ms - window_ms
        w_trades = [t for t in trades[:trade_idx] if t.ts_ms >= window_start]

        bid_depth_l5 = bk.bid_depth5 if hasattr(bk, 'bid_depth5') else bk.bid_depth1
        ask_depth_l5 = bk.ask_depth5 if hasattr(bk, 'ask_depth5') else bk.ask_depth1
        bid_depth_l10 = bk.bid_depth10 if hasattr(bk, 'bid_depth10') else bid_depth_l5
        ask_depth_l10 = bk.ask_depth10 if hasattr(bk, 'ask_depth10') else ask_depth_l5

        bid_queue_imb = (bid_depth_l5 - ask_depth_l5) / (bid_depth_l5 + ask_depth_l5 + 1e-9)
        ask_queue_imb = -bid_queue_imb
        multi_level_imb = (bid_depth_l10 - ask_depth_l10) / (bid_depth_l10 + ask_depth_l10 + 1e-9)
        depth_slope = (bid_depth_l5 / (ask_depth_l5 + 1e-9)) if ask_depth_l5 > 0 else 0.0

        best_bid = max(bk.bids) if bk.bids else 0.0
        best_ask = min(bk.asks) if bk.asks else 0.0
        qb = bk.bids.get(best_bid, 0.0) if best_bid else 0.0
        qa = bk.asks.get(best_ask, 0.0) if best_ask else 0.0
        if qb + qa > 0 and bk.mid and bk.mid > 0:
            microprice = (best_ask * qb + best_bid * qa) / (qb + qa)
            microprice_disp = (microprice - bk.mid) / bk.mid * 1e4
        else:
            microprice_disp = 0.0

        book_pressure = 0.0
        if hasattr(bk, 'adds') and hasattr(bk, 'cancels'):
            net_flow = (bk.adds or 0.0) - (bk.cancels or 0.0)
            gross_flow = abs(bk.adds or 0.0) + abs(bk.cancels or 0.0)
            if gross_flow > 1e-9:
                book_pressure = net_flow / gross_flow

        queue_imb_change = bid_queue_imb - prev_bid_imb
        prev_bid_imb = bid_queue_imb
        prev_ask_imb = ask_queue_imb

        event_intensity = len(w_trades) / (window_ms / 1000.0)

        rows.append({
            "ts_ms": bk.ts_ms,
            "bid_queue_imbalance": bid_queue_imb,
            "ask_queue_imbalance": ask_queue_imb,
            "multi_level_depth_imbalance": multi_level_imb,
            "depth_slope": depth_slope,
            "microprice_displacement": microprice_disp,
            "book_pressure": book_pressure,
            "queue_imbalance_change": queue_imb_change,
            "event_intensity": event_intensity,
        })

    return pd.DataFrame(rows)


def _compute_dynamics_and_regime(books: list, trades: list, ofi_df: pd.DataFrame | None = None, window_ms: int = 10000) -> pd.DataFrame:
    """Compute dynamics and regime features."""
    rows = []
    trade_idx = 0
    n_trades = len(trades)
    mids_hist = []
    ofi_lookup = {}
    if ofi_df is not None and not ofi_df.empty:
        for _, row in ofi_df.iterrows():
            ofi_lookup[int(row["ts_ms"])] = row.get("ofi_l1_best", 0.0)

    prev_ofi = 0.0
    prev_queue_imb = 0.0

    for i, bk in enumerate(books):
        while trade_idx < n_trades and trades[trade_idx].ts_ms <= bk.ts_ms:
            trade_idx += 1

        window_start = bk.ts_ms - window_ms
        w_trades = [t for t in trades[:trade_idx] if t.ts_ms >= window_start]

        mid = bk.mid if bk.mid else 0.0
        if mid > 0:
            mids_hist.append(mid)

        ofi = ofi_lookup.get(bk.ts_ms, prev_ofi)
        prev_ofi = ofi

        persistence = 0.0
        if len(mids_hist) >= 10:
            # Windowed persistence: correlation of last 10 mids vs previous 10 mids
            if len(mids_hist) >= 20:
                window_a = mids_hist[-10:]
                window_b = mids_hist[-20:-10]
                if len(window_a) == len(window_b):
                    try:
                        persistence = float(np.corrcoef(window_a, window_b)[0, 1])
                        if np.isnan(persistence):
                            persistence = 0.0
                    except Exception:
                        persistence = 0.0

        window_mids = [m for m in mids_hist[-int(window_ms / 1000 * 10):] if m is not None and m > 0]
        if len(window_mids) >= 3:
            rets = np.diff(np.log(np.array(window_mids)))
            short_term_vol = float(np.sqrt(np.sum(rets ** 2) * 1e4))
        else:
            short_term_vol = 0.0

        spread = bk.spread_bps if bk.spread_bps is not None else 0.0
        spread_regime = 1.0 if spread < 0.02 else 0.0
        vol_regime = 1.0 if short_term_vol > 0.5 else 0.0
        liq = bk.bid_depth1 + bk.ask_depth1
        liq_regime = 1.0 if liq > 1.0 else 0.0
        activity_regime = 1.0 if len(w_trades) > 5 else 0.0

        rows.append({
            "ts_ms": bk.ts_ms,
            "persistence": 0.0,
            "short_term_volatility": short_term_vol,
            "spread_regime_flag": spread_regime,
            "volatility_regime_flag": vol_regime,
            "liquidity_regime_flag": liq_regime,
            "activity_regime_flag": activity_regime,
        })

    return pd.DataFrame(rows)


def extract_v16_features(books: list, trades: list, window_ms: int = 10000) -> pd.DataFrame:
    """Extract all V16 event-time features: V14 base + V16-specific."""
    books = sorted(books, key=lambda b: b.ts_ms)
    trades = sorted(trades, key=lambda t: t.ts_ms)
    from app.v14.features import extract_v14_features as _extract_v14
    base_df = _extract_v14(books, trades, window_ms)
    if base_df.empty:
        return pd.DataFrame(columns=V16_FEATURES + ["ts_ms", "mid"])

    ofi_df = _compute_ofi(books, trades, window_ms)
    qb_df = _compute_queue_book_features(books, trades, window_ms)
    dyn_df = _compute_dynamics_and_regime(books, trades, ofi_df=ofi_df, window_ms=window_ms)

    # Drop columns that conflict with base_df (V14 features)
    base_cols = set(base_df.columns)
    for df in [ofi_df, qb_df, dyn_df]:
        drop_cols = [c for c in df.columns if c in base_cols and c != "ts_ms"]
        if drop_cols:
            df.drop(columns=drop_cols, inplace=True)

    merged = base_df.merge(ofi_df, on="ts_ms", how="outer") if not ofi_df.empty else base_df
    merged = merged.merge(qb_df, on="ts_ms", how="outer") if not qb_df.empty else merged
    merged = merged.merge(dyn_df, on="ts_ms", how="outer") if not dyn_df.empty else merged

    merged = merged.sort_values("ts_ms").reset_index(drop=True)
    merged = merged.replace([np.inf, -np.inf], 0.0).fillna(0.0)
    return merged


def build_v16_targets(df: pd.DataFrame, horizon_ms: int = 10000) -> pd.Series:
    """Binary target: mid-price rose by more than breakeven cost."""
    from app.v14.features import build_v14_targets
    return build_v14_targets(df, horizon_ms)


def build_v16_returns(df: pd.DataFrame, horizon_ms: int = 10000) -> pd.Series:
    """Return magnitude in bps."""
    from app.v14.features import build_v14_returns
    return build_v14_returns(df, horizon_ms)
