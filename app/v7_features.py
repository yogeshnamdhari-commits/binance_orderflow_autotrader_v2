"""V7 feature engineering — multi-dimensional microstructure features.

Computes research-supported features beyond the V5/V6 feature set:

  Multi-Level OFI       ofi_l1..l10, mlofi_weighted, ofi_decay_slope
  Queue Imbalance       qi_multi, qi_slope, qi_accel, queue_asymmetry
  Microprice Dynamics   mp_dev, mp_vel, mp_reversion_speed
  Trade-Flow Toxicity   vpin, kyle_lambda, signed_vol_imbalance
  Liquidity/Dynamics    depth_slope, spread_percentile, liq_regime_enc
  Volatility            vol_500, vol_ratio, vol_of_vol
  Cross-Level Interact  ofi_x_qi, mlofi_x_spread, depth_x_toxicity

All features are computed causally (from past events only) using the
V3/V4 base features already in v7_evidence_features.parquet.

Research basis:
  - Cont, Kukanov & Stoikov (2014): OFI and price impact
  - Xu, Gould & Howison (2017): Multi-level OFI
  - Gould & Bonart (2016): Queue imbalance as price predictor
  - Kolm, Turiel & Westray (2021): Deep order flow imbalance
  - Cartea, Jaimungal & Penalva (2015): Microprice dynamics
  - Easley, LdP & O'Hara (2012): Flow toxicity (VPIN)
"""

import numpy as np
import pandas as pd
from pathlib import Path
from typing import List, Optional


# V7 feature columns (new features beyond V5)
V7_MULTI_LEVEL_OFI = [
    "ofi_l2", "ofi_l3", "ofi_l5", "ofi_l10",
    "mlofi_weighted", "ofi_decay_slope"
]

V7_QUEUE_IMBALANCE = [
    "qi_multi", "qi_slope", "qi_accel", "queue_asymmetry"
]

V7_MICROPRICE = [
    "mp_dev", "mp_vel", "mp_reversion_speed"
]

V7_TOXICITY = [
    "vpin", "kyle_lambda", "signed_vol_imbalance"
]

V7_LIQUIDITY = [
    "depth_slope", "spread_percentile", "liq_regime_enc"
]

V7_VOLATILITY = [
    "vol_ratio", "vol_of_vol"
]

V7_INTERACTIONS = [
    "ofi_x_qi", "mlofi_x_spread", "depth_x_toxicity"
]

V7_NEW_FEATURES = (
    V7_MULTI_LEVEL_OFI + V7_QUEUE_IMBALANCE + V7_MICROPRICE +
    V7_TOXICITY + V7_LIQUIDITY + V7_VOLATILITY + V7_INTERACTIONS
)


def _compute_multi_level_ofi(df: pd.DataFrame) -> pd.DataFrame:
    """Compute multi-level OFI features from depth imbalance and OFI.
    
    Uses the relationship between OFI at L1 and depth imbalance at L5/L10
    to estimate multi-level order flow distribution.
    
    Research: Xu, Gould & Howison (2017) — multi-level OFI improves
    out-of-sample explanatory power.
    """
    df = df.copy()
    
    # Estimate per-level OFI using depth imbalance distribution
    # OFI at level L ≈ OFI_L1 * (depth_imbalance_L) / (sum of imbalance weights)
    ofi_l1 = df["ofi_l1"].to_numpy(float)
    di_l5 = df["di_l5"].to_numpy(float)
    di_l10 = df["di_l10"].to_numpy(float)
    
    # Multi-level OFI: distribute L1 OFI across levels using depth imbalance
    # Nearer levels get more weight (inverse level decay)
    df["ofi_l2"] = ofi_l1 * 0.5 * (1 + di_l5)
    df["ofi_l3"] = ofi_l1 * 0.3 * (1 + di_l5 * 0.8)
    df["ofi_l5"] = ofi_l1 * (di_l5 + 0.5) / 1.5
    df["ofi_l10"] = ofi_l1 * (di_l10 + 0.3) / 1.3
    
    # Weighted multi-level OFI (inverse level weights)
    weights = np.array([1.0, 0.8, 0.6, 0.4, 0.3, 0.2, 0.15, 0.1, 0.05, 0.02])
    ofi_levels = np.column_stack([
        ofi_l1,
        df["ofi_l2"].to_numpy(float),
        df["ofi_l3"].to_numpy(float),
        df["ofi_l5"].to_numpy(float) * 0.5,
        df["ofi_l5"].to_numpy(float) * 0.5,
        df["ofi_l10"].to_numpy(float) * 0.4,
        df["ofi_l10"].to_numpy(float) * 0.3,
        df["ofi_l10"].to_numpy(float) * 0.2,
        df["ofi_l10"].to_numpy(float) * 0.1,
        df["ofi_l10"].to_numpy(float) * 0.05,
    ])
    df["mlofi_weighted"] = np.sum(ofi_levels * weights, axis=1)
    
    # OFI decay slope: how concentrated is the flow at the top
    # Steep decay = localized at L1; flat = distributed
    ofi_abs = np.abs(ofi_levels)
    total_ofi = ofi_abs.sum(axis=1) + 1e-12
    df["ofi_decay_slope"] = ofi_abs[:, 0] / total_ofi
    
    return df


def _compute_queue_dynamics(df: pd.DataFrame) -> pd.DataFrame:
    """Compute queue imbalance dynamics.
    
    Research: Gould & Bonart (2016) — queue imbalance predicts
    one-tick-ahead price movement.
    """
    df = df.copy()
    
    qi_l1 = df["qi_l1"].to_numpy(float)
    di_l5 = df["di_l5"].to_numpy(float)
    di_l10 = df["di_l10"].to_numpy(float)
    
    # Multi-level queue imbalance (weighted average)
    df["qi_multi"] = 0.5 * qi_l1 + 0.3 * di_l5 + 0.2 * di_l10
    
    # Queue slope (rate of change) — causal rolling difference
    qi_slope = np.zeros(len(df))
    for i in range(1, min(10, len(df))):
        qi_slope[i] = qi_l1[i] - qi_l1[i-1]
    for i in range(10, len(df)):
        qi_slope[i] = qi_l1[i] - qi_l1[i-10]
    df["qi_slope"] = qi_slope
    
    # Queue acceleration (second derivative)
    qi_accel = np.zeros(len(df))
    for i in range(2, len(df)):
        qi_accel[i] = qi_slope[i] - qi_slope[i-1]
    df["qi_accel"] = qi_accel
    
    # Queue asymmetry: bid-side vs ask-side dynamics
    df["queue_asymmetry"] = qi_l1 * di_l5 - di_l5 * di_l10
    
    return df


def _compute_microprice_dynamics(df: pd.DataFrame) -> pd.DataFrame:
    """Compute microprice dynamics features.
    
    Research: Cartea, Jaimungal & Penalva (2015) — microprice
    is a better fair-price estimate; dislocation predicts reversion.
    """
    df = df.copy()
    
    # Microprice deviation (same as mpd_bps but explicit naming)
    df["mp_dev"] = df["mpd_bps"].to_numpy(float)
    
    # Microprice velocity (rate of change)
    mp_vel = np.zeros(len(df))
    mpd = df["mpd_bps"].to_numpy(float)
    for i in range(1, min(5, len(df))):
        mp_vel[i] = mpd[i] - mpd[i-1]
    for i in range(5, len(df)):
        mp_vel[i] = mpd[i] - mpd[i-5]
    df["mp_vel"] = mp_vel
    
    # Microprice reversion speed: how fast dislocation corrects
    # Negative of velocity (reversion = -velocity direction)
    df["mp_reversion_speed"] = -mp_vel * np.sign(mpd)
    
    return df


def _compute_toxicity(df: pd.DataFrame) -> pd.DataFrame:
    """Compute trade-flow toxicity features.
    
    Research: Easley, LdP & O'Hara (2012) — VPIN measures flow toxicity.
    """
    df = df.copy()
    
    # VPIN proxy: normalized absolute trade imbalance
    tfi = df["tfi_500"].to_numpy(float)
    signed_vol = df["signed_vol_500"].to_numpy(float)
    
    # VPIN-like: rolling average of |trade imbalance|
    vpin = np.zeros(len(df))
    for i in range(len(df)):
        start = max(0, i - 20)
        vpin[i] = np.mean(np.abs(tfi[start:i+1])) if i > 0 else 0.0
    df["vpin"] = vpin
    
    # Kyle's lambda proxy: price impact per unit volume
    mid = df["mid"].to_numpy(float)
    kyle = np.zeros(len(df))
    for i in range(1, len(df)):
        dmid = mid[i] - mid[i-1] if (mid[i] > 0 and mid[i-1] > 0) else 0.0
        vol = abs(signed_vol[i]) if np.isfinite(signed_vol[i]) else 1e-9
        kyle[i] = dmid / (vol + 1e-9)
    df["kyle_lambda"] = kyle
    
    # Signed volume imbalance (normalized)
    log_depth5 = df["log_depth5"].to_numpy(float)
    depth5 = np.expm1(log_depth5)
    df["signed_vol_imbalance"] = signed_vol / (depth5 + 1e-9)
    
    return df


def _compute_liquidity_dynamics(df: pd.DataFrame) -> pd.DataFrame:
    """Compute liquidity dynamics features."""
    df = df.copy()
    
    # Depth slope (same as depth_slope_bps but explicit)
    df["depth_slope"] = df["depth_slope_bps"].to_numpy(float)
    
    # Spread percentile (rank within session)
    spread = df["spread_bps"].to_numpy(float)
    spread_pct = np.zeros(len(df))
    for i in range(len(df)):
        start = max(0, i - 100)
        local = spread[start:i+1]
        if len(local) > 1:
            spread_pct[i] = np.sum(local <= spread[i]) / len(local)
        else:
            spread_pct[i] = 0.5
    df["spread_percentile"] = spread_pct
    
    # Liquidity regime encoding (numeric)
    regime_map = {"normal": 0, "high_impact": 1, "thin_book": -1}
    df["liq_regime_enc"] = df["regime"].map(regime_map).fillna(0).to_numpy(float)
    
    return df


def _compute_volatility_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute volatility dynamics features."""
    df = df.copy()
    
    vol_500 = df["vol_500"].to_numpy(float)
    vol_2000 = df["vol_2000"].to_numpy(float)
    
    # Vol ratio: short-term vol / long-term vol
    df["vol_ratio"] = vol_500 / (vol_2000 + 1e-9)
    
    # Vol of vol: rolling std of vol_500
    vol_of_vol = np.zeros(len(df))
    for i in range(len(df)):
        start = max(0, i - 20)
        local = vol_500[start:i+1]
        if len(local) > 2:
            vol_of_vol[i] = np.std(local)
        else:
            vol_of_vol[i] = 0.0
    df["vol_of_vol"] = vol_of_vol
    
    return df


def _compute_interactions(df: pd.DataFrame) -> pd.DataFrame:
    """Compute cross-level interaction features."""
    df = df.copy()
    
    # OFI × queue imbalance
    df["ofi_x_qi"] = df["ofi_l1"].to_numpy(float) * df["qi_l1"].to_numpy(float)
    
    # MLOFI × spread
    df["mlofi_x_spread"] = df["mlofi_weighted"].to_numpy(float) * df["spread_bps"].to_numpy(float)
    
    # Depth × toxicity
    log_depth5 = df["log_depth5"].to_numpy(float)
    depth5 = np.expm1(log_depth5)
    vpin = df["vpin"].to_numpy(float)
    df["depth_x_toxicity"] = depth5 * vpin
    
    return df


def add_v7_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add all V7 features to the dataframe.
    
    Args:
        df: DataFrame with V3/V4 base features (from v7_evidence_features.parquet)
    
    Returns:
        DataFrame with additional V7 feature columns.
    """
    df = df.copy()
    
    # Ensure required base features exist
    required = ["ofi_l1", "qi_l1", "di_l5", "di_l10", "mpd_bps", "tfi_500",
                "signed_vol_500", "mid", "spread_bps", "depth_slope_bps",
                "log_depth5", "vol_500", "regime"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required base features: {missing}")
    
    # Add vol_2000 if not present
    if "vol_2000" not in df.columns:
        df["vol_2000"] = df["vol_500"] * 1.5  # Approximate
    
    # Compute feature groups
    df = _compute_multi_level_ofi(df)
    df = _compute_queue_dynamics(df)
    df = _compute_microprice_dynamics(df)
    df = _compute_toxicity(df)
    df = _compute_liquidity_dynamics(df)
    df = _compute_volatility_features(df)
    df = _compute_interactions(df)
    
    # Replace inf/nan with 0
    for col in V7_NEW_FEATURES:
        if col in df.columns:
            df[col] = df[col].replace([np.inf, -np.inf], 0).fillna(0)
    
    return df


def build_v7_features(feature_path: str | Path, out_path: str | Path) -> Path:
    """Build V7 features from base features and save to parquet.
    
    Args:
        feature_path: Path to v7_evidence_features.parquet
        out_path: Output path for v7_features.parquet
    
    Returns:
        Path to output file.
    """
    feature_path = Path(feature_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    df = pd.read_parquet(feature_path)
    df = add_v7_features(df)
    df.to_parquet(out_path, index=False)
    
    return out_path


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", type=Path,
                    default=Path("data/research/v7_evidence_features.parquet"))
    ap.add_argument("--out", type=Path,
                    default=Path("data/research/v7_features.parquet"))
    a = ap.parse_args()
    p = build_v7_features(a.features, a.out)
    print(f"Wrote V7 features: {p}")
    print(f"Shape: {pd.read_parquet(p).shape}")
    print(f"New features: {V7_NEW_FEATURES}")
