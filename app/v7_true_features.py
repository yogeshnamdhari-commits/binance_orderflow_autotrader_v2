"""V7 true multi-level features from v4 level snapshots.

Reads derived_v4.jsonl files (which contain levels_bid/levels_ask per event)
and computes TRUE multi-level OFI, queue imbalance, and dynamics features.

This is the correct way to compute multi-level features: from actual level
snapshots, not from aggregated V3 features.

Research basis:
  - Xu, Gould & Howison (2017): Multi-level OFI from actual level changes
  - Cont, Kukanov & Stoikov (2014): OFI definition per level
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from typing import List, Dict


def compute_multi_level_ofi(levels_bid_prev, levels_ask_prev,
                           levels_bid_curr, levels_ask_curr):
    """Compute multi-level OFI from consecutive level snapshots.
    
    OFI at level L = sum of signed qty changes at that price level.
    Returns per-level OFI and weighted aggregate.
    """
    # Convert to dicts for easy lookup
    bid_prev = {p: q for p, q in levels_bid_prev}
    ask_prev = {p: q for p, q in levels_ask_prev}
    bid_curr = {p: q for p, q in levels_bid_curr}
    ask_curr = {p: q for p, q in levels_ask_curr}
    
    # All prices that appear in current or previous
    all_bid_prices = set(list(bid_prev.keys()) + list(bid_curr.keys()))
    all_ask_prices = set(list(ask_prev.keys()) + list(ask_curr.keys()))
    
    # Compute per-level OFI (signed changes)
    ofi_bid = 0.0
    for p in all_bid_prices:
        curr = bid_curr.get(p, 0.0)
        prev = bid_prev.get(p, 0.0)
        ofi_bid += curr - prev
    
    ofi_ask = 0.0
    for p in all_ask_prices:
        curr = ask_curr.get(p, 0.0)
        prev = ask_prev.get(p, 0.0)
        ofi_ask += curr - prev
    
    # Net OFI = bid changes - ask changes
    ofi_net = ofi_bid - ofi_ask
    
    # Per-level OFI (using top-10 levels)
    ofi_levels = []
    for i in range(10):
        p_bid = levels_bid_curr[i][0] if i < len(levels_bid_curr) else None
        p_ask = levels_ask_curr[i][0] if i < len(levels_ask_curr) else None
        
        bid_change = 0.0
        if p_bid is not None:
            curr = levels_bid_curr[i][1] if i < len(levels_bid_curr) else 0.0
            prev = bid_prev.get(p_bid, 0.0)
            bid_change = curr - prev
        
        ask_change = 0.0
        if p_ask is not None:
            curr = levels_ask_curr[i][1] if i < len(levels_ask_curr) else 0.0
            prev = ask_prev.get(p_ask, 0.0)
            ask_change = curr - prev
        
        ofi_levels.append(bid_change - ask_change)
    
    # Weighted multi-level OFI (inverse level weights)
    weights = [1.0 / (i + 1) for i in range(10)]
    mlofi_weighted = sum(w * ofi for w, ofi in zip(weights, ofi_levels))
    
    # OFI decay: concentration at top vs distributed
    abs_ofi = [abs(o) for o in ofi_levels]
    total_ofi = sum(abs_ofi) + 1e-12
    ofi_decay = abs_ofi[0] / total_ofi if total_ofi > 0 else 0.0
    
    return {
        "ofi_net": ofi_net,
        "ofi_bid_total": ofi_bid,
        "ofi_ask_total": ofi_ask,
        "ofi_levels": ofi_levels,
        "mlofi_weighted": mlofi_weighted,
        "ofi_decay": ofi_decay,
    }


def compute_queue_features(levels_bid, levels_ask):
    """Compute multi-level queue imbalance features."""
    bid_qty = [q for _, q in levels_bid]
    ask_qty = [q for _, q in levels_ask]
    
    # Pad to 10 levels
    while len(bid_qty) < 10:
        bid_qty.append(0.0)
    while len(ask_qty) < 10:
        ask_qty.append(0.0)
    
    # L1 queue imbalance
    d1 = bid_qty[0] + ask_qty[0]
    qi_l1 = (bid_qty[0] - ask_qty[0]) / d1 if d1 > 0 else 0.0
    
    # Multi-level queue imbalance (weighted)
    weights = [1.0 / (i + 1) for i in range(10)]
    qi_multi = sum(w * (b - a) / (b + a + 1e-9) 
                   for w, b, a in zip(weights, bid_qty, ask_qty))
    
    # Depth slope from levels
    log_qty = [np.log1p(q) for q in bid_qty + ask_qty]
    depth_slope = float(np.polyfit(range(len(log_qty)), log_qty, 1)[0]) if len(log_qty) > 1 else 0.0
    
    # Depth asymmetry
    bid_total = sum(bid_qty)
    ask_total = sum(ask_qty)
    depth_asym = (bid_total - ask_total) / (bid_total + ask_total + 1e-9)
    
    return {
        "qi_l1_levels": qi_l1,
        "qi_multi": qi_multi,
        "depth_slope_levels": depth_slope,
        "depth_asymmetry": depth_asym,
    }


def build_v7_from_v4(session_dirs: List[Path], out_path: str | Path) -> Path:
    """Build V7 features from v4 derived files with level snapshots.
    
    Computes true multi-level OFI from consecutive level snapshots.
    Combines with V3 base features for the full feature set.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    all_rows = []
    
    for sd in sorted(session_dirs):
        dv4 = sd / "derived_v4.jsonl"
        if not dv4.exists():
            continue
        
        rows = [json.loads(l) for l in dv4.open() if l.strip()]
        if len(rows) < 2:
            continue
        
        # Initialize with first event's levels
        prev_bids = rows[0].get("levels_bid", [])
        prev_asks = rows[0].get("levels_ask", [])
        
        for i, row in enumerate(rows):
            # Current levels
            curr_bids = row.get("levels_bid", [])
            curr_asks = row.get("levels_ask", [])
            
            if not curr_bids or not curr_asks:
                curr_bids = prev_bids
                curr_asks = prev_asks
            
            # Compute multi-level OFI from level snapshots
            ofi_features = compute_multi_level_ofi(prev_bids, prev_asks, curr_bids, curr_asks)
            
            # Compute queue features from current levels
            queue_features = compute_queue_features(curr_bids, curr_asks)
            
            # Store enhanced row
            enhanced = dict(row)
            enhanced["session"] = sd.name
            enhanced["mlofi_weighted"] = ofi_features["mlofi_weighted"]
            enhanced["ofi_decay"] = ofi_features["ofi_decay"]
            enhanced["ofi_net_levels"] = ofi_features["ofi_net"]
            enhanced["qi_multi"] = queue_features["qi_multi"]
            enhanced["depth_slope_levels"] = queue_features["depth_slope_levels"]
            enhanced["depth_asymmetry"] = queue_features["depth_asymmetry"]
            
            # Per-level OFI (L2-L10)
            ofi_levels = ofi_features["ofi_levels"]
            for j in range(2, 11):
                enhanced[f"ofi_l{j}"] = ofi_levels[j-1] if j-1 < len(ofi_levels) else 0.0
            
            # Queue imbalance at multiple levels
            bid_qty = [q for _, q in curr_bids] + [0.0] * 10
            ask_qty = [q for _, q in curr_asks] + [0.0] * 10
            for level in [2, 3, 5, 10]:
                n = min(level, len(bid_qty), len(ask_qty))
                b = sum(bid_qty[:n])
                a = sum(ask_qty[:n])
                enhanced[f"qi_l{level}"] = (b - a) / (b + a + 1e-9) if (b + a) > 0 else 0.0
            
            # Update previous levels
            prev_bids = curr_bids
            prev_asks = curr_asks
            
            all_rows.append(enhanced)
    
    if not all_rows:
        raise ValueError("No rows processed from v4 files")
    
    df = pd.DataFrame(all_rows)
    # Ensure seq is string for parquet compatibility
    if "seq" in df.columns:
        df["seq"] = df["seq"].astype(str)
    # Drop raw level/trade columns (not needed for modeling)
    drop_cols = ["levels_bid", "levels_ask", "trade_price", "trade_qty", "trade_maker"]
    df = df.drop(columns=[c for c in drop_cols if c in df.columns])
    df.to_parquet(out_path, index=False)
    
    return out_path


def add_v7_dynamic_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add dynamic features (velocity, acceleration, toxicity) to V7 data.
    
    These are computed from time-series of existing features.
    """
    df = df.copy()
    
    # Microprice velocity (from mpd_bps)
    mpd = df["mpd_bps"].to_numpy(float) if "mpd_bps" in df.columns else np.zeros(len(df))
    mp_vel = np.zeros(len(df))
    for i in range(5, len(df)):
        mp_vel[i] = mpd[i] - mpd[i-5]
    df["mp_vel"] = mp_vel
    df["mp_reversion"] = -mp_vel * np.sign(mpd)
    
    # Queue slope (from qi_l1)
    qi = df["qi_l1"].to_numpy(float) if "qi_l1" in df.columns else np.zeros(len(df))
    qi_slope = np.zeros(len(df))
    for i in range(10, len(df)):
        qi_slope[i] = qi[i] - qi[i-10]
    df["qi_slope"] = qi_slope
    df["qi_accel"] = np.diff(qi_slope, prepend=0)
    
    # VPIN proxy
    tfi = df["tfi_500"].to_numpy(float) if "tfi_500" in df.columns else np.zeros(len(df))
    vpin = np.zeros(len(df))
    for i in range(len(df)):
        start = max(0, i - 20)
        local = tfi[start:i+1]
        vpin[i] = np.mean(np.abs(local)) if len(local) > 0 else 0.0
    df["vpin"] = vpin
    
    # Kyle's lambda proxy
    mid = df["mid"].to_numpy(float) if "mid" in df.columns else np.zeros(len(df))
    signed_vol = df["signed_vol_500"].to_numpy(float) if "signed_vol_500" in df.columns else np.zeros(len(df))
    kyle = np.zeros(len(df))
    for i in range(1, len(df)):
        dmid = (mid[i] - mid[i-1]) if (mid[i] > 0 and mid[i-1] > 0) else 0.0
        vol = abs(signed_vol[i]) if np.isfinite(signed_vol[i]) else 1e-9
        kyle[i] = dmid / (vol + 1e-9)
    df["kyle_lambda"] = kyle
    
    # Volatility ratio
    vol_500 = df["vol_500"].to_numpy(float) if "vol_500" in df.columns else np.zeros(len(df))
    vol_2000 = df["vol_2000"].to_numpy(float) if "vol_2000" in df.columns else vol_500 * 1.5
    df["vol_ratio"] = vol_500 / (vol_2000 + 1e-9)
    
    # Signed volume imbalance
    log_d5 = df["log_depth5"].to_numpy(float) if "log_depth5" in df.columns else np.zeros(len(df))
    d5 = np.expm1(log_d5)
    df["signed_vol_imbalance"] = signed_vol / (d5 + 1e-9)
    
    # Cross-level interactions
    ofi = df["ofi_l1"].to_numpy(float) if "ofi_l1" in df.columns else np.zeros(len(df))
    df["ofi_x_qi"] = ofi * qi
    df["mlofi_x_spread"] = df.get("mlofi_weighted", ofi) * df["spread_bps"].to_numpy(float) if "spread_bps" in df.columns else np.zeros(len(df))
    
    # Replace inf/nan
    for col in ["mp_vel", "mp_reversion", "qi_slope", "qi_accel", "vpin", "kyle_lambda",
                "vol_ratio", "signed_vol_imbalance", "ofi_x_qi", "mlofi_x_spread"]:
        if col in df.columns:
            df[col] = df[col].replace([np.inf, -np.inf], 0).fillna(0)
    
    return df


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--v4-dirs", nargs="+", type=Path,
                    default=None,
                    help="V4 session directories (default: auto-detect from data/live/v4)")
    ap.add_argument("--out", type=Path,
                    default=Path("data/research/v7_true_features.parquet"))
    a = ap.parse_args()
    
    if a.v4_dirs is None:
        v4_root = Path("data/live/v4")
        session_dirs = sorted([d for d in v4_root.glob("2026*") if d.is_dir()])
    else:
        session_dirs = a.v4_dirs
    
    print(f"Processing {len(session_dirs)} sessions...")
    p = build_v7_from_v4(session_dirs, a.out)
    df = pd.read_parquet(p)
    print(f"Built V7 features: {p}")
    print(f"Shape: {df.shape}")
    print(f"Columns: {df.columns.tolist()}")
