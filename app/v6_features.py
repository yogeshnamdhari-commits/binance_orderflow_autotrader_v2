"""V6 microstructure features — research module.

Implements pre-registered hypothesis features NOT captured by V5.
All features use only causally available information (no lookahead).
"""

import numpy as np
import pandas as pd

# Exports expected by existing tests
V5_FEATURES = ["ofi_l1", "ofi_norm_l1", "qi_l1", "di_l5", "di_l10",
               "mpd_bps", "spread_bps", "bid_cancel_bps", "ask_add_bps",
               "cancel_pressure", "tfi_500", "liq_depletion",
               "log_depth1", "log_depth5", "log_event_rate",
               "depth_slope_bps", "vol_500"]

V6_FEATURES = [
    # V5 features (included for completeness)
    "ofi_l1", "ofi_norm_l1", "qi_l1", "di_l5", "di_l10",
    "mpd_bps", "spread_bps", "bid_cancel_bps", "ask_add_bps",
    "cancel_pressure", "tfi_500", "liq_depletion",
    "log_depth1", "log_depth5", "log_event_rate",
    "depth_slope_bps", "vol_500",
    # V6 new features
    "ofi_slope",
    "ofi_persistence",
    "di_l1_3",
    "di_l4_7",
    "di_l8_10",
    "imbalance_slope",
    "vpin_500",
    "trade_size_kyle",
    "signed_vol_momentum",
    "cvd_slope",
    "cvd_price_divergence",
    "cvd_acceleration",
    "absorption_proxy",
    "depth_recovery_rate",
    "impact_per_volume",
    "liquidity_regime",
    "depth_regime",
    "vol_regime",
    "price_response_to_ofi",
    "microprice_momentum",
    "effective_spread",
    "contemporaneous_cost_gate",
    "cost_adjusted_signal",
    # V6.1 additional features (Phase 2)
    "absorption_ratio",
    "vamp_deviation",
    "resiliency",
    "convexity",
    "flow_persistence",
    "spread_regime",
    "flow_pressure",
]

PRIMARY_HORIZON = 500


def compute_v6_features(df):
    """Compute all V6 features from derived_v5 data."""
    df = df.sort_values(['session', 'ts_ms']).reset_index(drop=True)
    
    # H1: Liquidity Absorption Ratio
    depth_l1 = np.exp(df['log_depth1'].values)
    signed_vol = df['signed_vol_500'].values
    df['absorption_ratio'] = np.where(depth_l1 > 0, np.abs(signed_vol) / depth_l1, 0.0)
    df['absorption_proxy'] = df['absorption_ratio']
    
    # H2: Multi-Level Microprice (VAMP proxy)
    df['vamp_deviation'] = df['mpd_bps'] * (1 + df['di_l5'].fillna(0))
    df['microprice_momentum'] = df.groupby('session')['mpd_bps'].diff(5)
    
    # H3: Depth Resiliency
    resiliency_list = []
    for sess, grp in df.groupby('session'):
        d = grp['log_depth1'].values
        r = np.full(len(d), np.nan)
        lag = 5
        if len(d) > lag:
            r[lag:] = (d[lag:] - d[:-lag]) / (d[:-lag] + 1e-10)
        resiliency_list.extend(r)
    df['resiliency'] = resiliency_list
    df['depth_recovery_rate'] = df['resiliency']
    
    # H4: Book Shape Convexity
    depth_l5 = np.exp(df['log_depth5'].values)
    df['convexity'] = np.where(depth_l1 > 0, (depth_l5 - depth_l1) / depth_l1, 0.0)
    df['imbalance_slope'] = df.groupby('session')['qi_l1'].diff(5)
    
    # H5: Flow Persistence
    persistence_list = []
    for sess, grp in df.groupby('session'):
        tfi = grp['tfi_500'].values
        p = np.full(len(tfi), np.nan)
        window = 20
        for i in range(window, len(tfi)):
            segment = tfi[i-window:i]
            if np.std(segment) > 1e-10:
                p[i] = np.corrcoef(segment[:-1], segment[1:])[0, 1]
            else:
                p[i] = 0.0
        persistence_list.extend(p)
    df['flow_persistence'] = persistence_list
    df['ofi_persistence'] = df['flow_persistence']
    df['ofi_slope'] = df.groupby('session')['ofi_l1'].diff(5)
    
    # H6: Spread Regime
    spread_regime_list = []
    for sess, grp in df.groupby('session'):
        s = grp['spread_bps'].values
        sr = np.full(len(s), np.nan)
        window = 100
        for i in range(window, len(s)):
            mean_s = np.mean(s[i-window:i])
            if mean_s > 1e-10:
                sr[i] = s[i] / mean_s
            else:
                sr[i] = 1.0
        spread_regime_list.extend(sr)
    df['spread_regime'] = spread_regime_list
    df['effective_spread'] = df['spread_bps']
    
    # H7: Flow Pressure
    df['flow_pressure'] = df['log_event_rate'].fillna(0) * df['tfi_500'].abs()
    df['price_response_to_ofi'] = df['tfi_500'] * df['ofi_l1']
    
    # Additional V6 features
    df['di_l1_3'] = df['qi_l1']
    df['di_l4_7'] = df['di_l5']
    df['di_l8_10'] = df['di_l10']
    
    # VPIN proxy
    vpin_list = []
    for sess, grp in df.groupby('session'):
        vol = grp['signed_vol_500'].abs().values
        v = np.full(len(vol), np.nan)
        window = 20
        for i in range(window, len(vol)):
            seg = vol[i-window:i]
            buy = np.sum(seg[seg > 0])
            sell = np.sum(-seg[seg < 0])
            total = buy + sell
            if total > 0:
                v[i] = abs(buy - sell) / total
        vpin_list.extend(v)
    df['vpin_500'] = vpin_list
    
    # Trade size Kyle's lambda proxy
    df['trade_size_kyle'] = df['signed_vol_500'].abs() / (df['log_depth1'] + 0.01)
    
    # Signed vol momentum
    df['signed_vol_momentum'] = df.groupby('session')['signed_vol_500'].diff(5)
    
    # CVD features
    if 'cvd' in df.columns:
        df['cvd_slope'] = df.groupby('session')['cvd'].diff(5)
        df['cvd_acceleration'] = df.groupby('session')['cvd_slope'].diff(3)
        df['cvd_price_divergence'] = df['cvd_slope'] * df['tfi_500']
    else:
        df['cvd_slope'] = 0.0
        df['cvd_acceleration'] = 0.0
        df['cvd_price_divergence'] = 0.0
    
    # Impact per volume
    df['impact_per_volume'] = df['mpd_bps'] / (df['signed_vol_500'].abs() + 0.01)
    
    # Regime variables
    df['liquidity_regime'] = pd.qcut(df['log_depth5'].rank(method='first'), 
                                      q=3, labels=['low', 'mid', 'high'],
                                      duplicates='drop').astype(str)
    df['depth_regime'] = pd.qcut(df['log_depth1'].rank(method='first'),
                                  q=3, labels=['thin', 'normal', 'deep'],
                                  duplicates='drop').astype(str)
    df['vol_regime'] = pd.qcut(df['vol_500'].rank(method='first'),
                                q=3, labels=['low', 'mid', 'high'],
                                duplicates='drop').astype(str)
    
    # Cost-adjusted signal
    df['contemporaneous_cost_gate'] = df['spread_bps'] + 2.0
    df['cost_adjusted_signal'] = df['tfi_500'] / (df['contemporaneous_cost_gate'] + 0.01)
    
    return df


def get_v6_feature_names():
    """Return list of V6 feature column names."""
    return V6_FEATURES


def add_v6_features(df):
    """Add V6 features to DataFrame (alias for compute_v6_features)."""
    return compute_v6_features(df)


if __name__ == '__main__':
    from app.v3_labels import add_labels
    df = pd.read_parquet('data/research/v5_evidence_features.parquet')
    df = add_labels(df, (500,))
    df = compute_v6_features(df)
    
    print("V6 features computed:")
    for feat in get_v6_feature_names():
        if feat in df.columns:
            valid = df[feat].notna().sum()
            print(f"  {feat}: valid={valid}")
