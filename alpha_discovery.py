#!/usr/bin/env python3
"""Alpha Discovery: Compute and evaluate 7 pre-registered information-set hypotheses.

All features use only causally available information.
Evaluated on chronological OOS data.
"""
import json, sys, warnings, time
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats as scs

warnings.filterwarnings('ignore')
sys.path.insert(0, '.')

from app.v3_labels import add_labels
from app.v5_cost import measured_gate

TAKER_COST = measured_gate()
MAKER_COST = 2.0
ALPHA = 0.05 / 7  # Bonferroni for 7 hypotheses
HORIZON = 500

def block_bootstrap_ci(values, block_size=50, n_boot=2000, alpha=0.05, seed=42):
    rng = np.random.RandomState(seed)
    n = len(values)
    if n == 0:
        return 0.0, 0.0, 0.0, (0.0, 0.0)
    values = np.array(values)
    n_blocks = max(1, int(np.ceil(n / block_size)))
    boot_means = np.empty(n_boot)
    for i in range(n_boot):
        starts = rng.randint(0, n, size=n_blocks)
        sample = np.concatenate([values[s:s+block_size] for s in starts])[:n]
        boot_means[i] = np.mean(sample)
    lo = np.percentile(boot_means, alpha/2 * 100)
    hi = np.percentile(boot_means, (1 - alpha/2) * 100)
    mean = float(np.mean(values))
    if n > 1:
        t = mean / (np.std(values, ddof=1) / np.sqrt(n))
        p = 2 * min(float(scs.t.cdf(t, n-1)), 1 - float(scs.t.cdf(t, n-1)))
    else:
        t, p = 0.0, 1.0
    return mean, t, p, (float(lo), float(hi))

def compute_features(df):
    """Compute all 7 hypothesis features."""
    df = df.sort_values(['session', 'ts_ms']).reset_index(drop=True)
    
    # H1: Order-Book Resiliency
    # Proxy: change in log_depth1 over 500ms after each event
    df['resiliency_500'] = df.groupby('session')['log_depth1'].diff(5)
    
    # H2: Flow Persistence (autocorrelation of tfi_500)
    # Proxy: correlation of tfi_500 with its lag-1 over rolling window
    def rolling_autocorr(x, window=20):
        if len(x) < window:
            return np.nan
        return x.autocorr(lag=1)
    df['flow_persistence'] = df.groupby('session')['tfi_500'].rolling(20, min_periods=10).apply(rolling_autocorr, raw=False).reset_index(level=0, drop=True)
    
    # H3: Depth Concentration
    df['depth_concentration'] = np.exp(df['log_depth1']) / np.exp(df['log_depth5'])
    
    # H4: Spread Transition
    df['spread_change'] = df.groupby('session')['spread_bps'].diff(5)
    
    # H5: Price-Impact Normalized Flow
    df['normalized_flow'] = df['tfi_500'] / (df['log_depth5'] + 0.01)
    
    # H6: Event Clustering (coefficient of variation of inter-event times)
    df['inter_event_time'] = df.groupby('session')['ts_ms'].diff().dt.total_seconds() if hasattr(df['ts_ms'], 'dt') else df.groupby('session')['ts_ms'].diff()
    # Convert to seconds
    df['inter_event_time_s'] = df['inter_event_time'] / 1000.0
    # Rolling CV
    def rolling_cv(x, window=20):
        if len(x) < window:
            return np.nan
        return x.std() / x.mean() if x.mean() > 0 else np.nan
    df['event_clustering'] = df.groupby('session')['inter_event_time_s'].rolling(20, min_periods=10).apply(rolling_cv, raw=False).reset_index(level=0, drop=True)
    
    # H7: Large Trade Direction (proxy using signed_vol_500)
    # Large trade = top decile of signed_vol_500 magnitude
    threshold = df['signed_vol_500'].abs().quantile(0.9)
    df['large_trade_direction'] = np.where(
        df['signed_vol_500'].abs() > threshold,
        np.sign(df['signed_vol_500']),
        0
    )
    
    return df

def evaluate_hypothesis(df, feature_name, direction='above', threshold=None):
    """Evaluate a single hypothesis."""
    if feature_name not in df.columns:
        return None
    
    feature = df[feature_name]
    target = df[f'r_{HORIZON}']
    
    if threshold is None:
        threshold = feature.quantile(0.7)
    
    # Select signals
    if direction == 'above':
        mask = feature > threshold
    elif direction == 'below':
        mask = feature < threshold
    else:
        mask = feature.abs() > threshold
    
    valid = mask & feature.notna() & target.notna()
    
    if valid.sum() < 50:
        return None
    
    selected = df.loc[valid]
    gross = selected[f'r_{HORIZON}'].values
    
    mean_g, t_g, p_g, ci_g = block_bootstrap_ci(gross)
    net_taker = mean_g - TAKER_COST
    net_maker = mean_g - MAKER_COST
    
    by_session = selected.groupby('session')[f'r_{HORIZON}'].mean()
    sessions_positive = (by_session > 0).sum()
    
    return {
        'feature': feature_name,
        'threshold': threshold,
        'n_signals': int(valid.sum()),
        'gross_bps': mean_g,
        't_stat': t_g,
        'p_value': p_g,
        'ci_low': ci_g[0],
        'ci_high': ci_g[1],
        'net_taker_bps': net_taker,
        'net_maker_bps': net_maker,
        'sessions_positive': int(sessions_positive),
        'total_sessions': len(by_session),
        'frac_positive': (gross > 0).mean(),
    }

def main():
    print("=" * 70)
    print("ALPHA DISCOVERY: INFORMATION-SET EXPANSION")
    print("=" * 70)
    print(f"Bonferroni-corrected α = {ALPHA:.5f}")
    print(f"Horizon: {HORIZON}ms")
    print()
    
    # Load data
    df = pd.read_parquet('data/research/v5_evidence_features.parquet')
    df = add_labels(df, (HORIZON,))
    
    # Split
    sessions = sorted(df['session'].unique())
    n_train = int(len(sessions) * 0.6)
    oos_sessions = sessions[n_train:]
    df_oos = df[df['session'].isin(oos_sessions)].copy()
    
    print(f"Total sessions: {len(sessions)}")
    print(f"OOS sessions: {len(oos_sessions)}")
    print(f"OOS events: {len(df_oos)}")
    print()
    
    # Compute features
    print("Computing hypothesis features...")
    df_oos = compute_features(df_oos)
    
    # Evaluate hypotheses
    print("\nEvaluating hypotheses...")
    results = []
    
    hypotheses = [
        ('H1: Resiliency', 'resiliency_500', 'above', None),
        ('H2: Flow Persistence', 'flow_persistence', 'above', None),
        ('H3: Depth Concentration', 'depth_concentration', 'above', None),
        ('H4: Spread Change', 'spread_change', 'below', None),  # Narrowing spread = safer
        ('H5: Normalized Flow', 'normalized_flow', 'above', None),
        ('H6: Event Clustering', 'event_clustering', 'above', None),
        ('H7: Large Trade Direction', 'large_trade_direction', 'above', 0),
    ]
    
    for name, feature, direction, threshold in hypotheses:
        r = evaluate_hypothesis(df_oos, feature, direction, threshold)
        if r:
            r['name'] = name
            results.append(r)
            print(f"  {name}: n={r['n_signals']}, gross={r['gross_bps']:.4f}, p={r['p_value']:.4f}")
        else:
            print(f"  {name}: insufficient signals")
    
    # Print results
    print(f"\n{'='*70}")
    print("RESULTS")
    print(f"{'='*70}")
    
    for r in results:
        print(f"\n{r['name']}")
        print(f"  Feature: {r['feature']}")
        print(f"  Signals: {r['n_signals']}")
        print(f"  Gross: {r['gross_bps']:.6f} bps")
        print(f"  t-stat: {r['t_stat']:.4f}, p-value: {r['p_value']:.6f}")
        print(f"  95% CI: [{r['ci_low']:.6f}, {r['ci_high']:.6f}] bps")
        print(f"  Net (taker): {r['net_taker_bps']:.6f} bps")
        print(f"  Net (maker): {r['net_maker_bps']:.6f} bps")
        print(f"  Sessions positive: {r['sessions_positive']}/{r['total_sessions']}")
        
        passes = (r['p_value'] < ALPHA and 
                  r['net_maker_bps'] > 0 and 
                  r['sessions_positive'] / r['total_sessions'] > 0.6)
        print(f"  Passes gate: {passes}")
    
    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY TABLE")
    print(f"{'='*70}")
    print(f"{'Hypothesis':<30} {'N':>6} {'Gross':>8} {'p-val':>8} {'Net(M)':>8} {'Pass':>6}")
    print(f"{'-'*60}")
    for r in results:
        passes = (r['p_value'] < ALPHA and 
                  r['net_maker_bps'] > 0 and 
                  r['sessions_positive'] / r['total_sessions'] > 0.6)
        print(f"{r['name']:<30} {r['n_signals']:>6} {r['gross_bps']:>8.4f} {r['p_value']:>8.4f} {r['net_maker_bps']:>8.4f} {'YES' if passes else 'NO':>6}")
    
    # Save
    results_df = pd.DataFrame(results)
    results_df.to_csv('data/research/alpha_discovery_results.csv', index=False)
    
    # Final
    any_passes = any(
        r['p_value'] < ALPHA and 
        r['net_maker_bps'] > 0 and 
        r['sessions_positive'] / r['total_sessions'] > 0.6
        for r in results
    )
    
    print(f"\n{'='*70}")
    if any_passes:
        print("FINAL: At least one hypothesis passes the economic gate")
    else:
        print("FINAL: NO hypothesis passes the economic gate")
        print("Classification: INFORMATION SET ECONOMICALLY INSUFFICIENT")
    print(f"{'='*70}")

if __name__ == "__main__":
    main()
