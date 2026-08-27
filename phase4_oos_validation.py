#!/usr/bin/env python3
"""PHASE 4: Strict OOS Validation — Optimized version."""
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
ALPHA = 0.05 / 3
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

def main():
    print("=" * 70)
    print("PHASE 4: STRICT OOS VALIDATION")
    print("=" * 70)
    print(f"Bonferroni-corrected α = {ALPHA:.5f}")
    print(f"Horizon: {HORIZON}ms")
    print()
    
    # Load data
    df = pd.read_parquet('data/research/v5_evidence_features.parquet')
    df = add_labels(df, (HORIZON,))
    
    # Split: chronological OOS
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
    
    # Hypothesis A: VPIN (simplified using existing tfi_500)
    # VPIN proxy: |tfi_500| high = toxic flow
    df_oos['vpin_proxy'] = df_oos['tfi_500'].abs()
    
    # Hypothesis B: Multi-Level Imbalance Interaction
    df_oos['imbalance_interaction'] = df_oos['qi_l1'] * df_oos['di_l5']
    
    # Hypothesis C: Size-Weighted Flow (proxy using signed_vol * tfi)
    df_oos['size_weighted_tfi'] = df_oos['tfi_500'] * df_oos['signed_vol_500'].abs()
    
    # Evaluate each hypothesis
    results = []
    
    # --- Hypothesis A: VPIN > threshold ---
    print("\nEvaluating Hypothesis A: Order Flow Toxicity...")
    threshold_a = df_oos['vpin_proxy'].quantile(0.9)
    mask_a = (df_oos['vpin_proxy'] > threshold_a) & df_oos[f'r_{HORIZON}'].notna()
    if mask_a.sum() > 50:
        # High toxicity predicts reversal, so flip direction
        gross_a = -df_oos.loc[mask_a, f'r_{HORIZON}'].values
        mean_g, t_g, p_g, ci_g = block_bootstrap_ci(gross_a)
        by_sess = df_oos.loc[mask_a].groupby('session')[f'r_{HORIZON}'].mean()
        sess_pos = (-by_sess > 0).sum()
        
        results.append({
            'name': 'A: Order Flow Toxicity (VPIN)',
            'feature': 'vpin_proxy',
            'threshold': threshold_a,
            'n_signals': int(mask_a.sum()),
            'gross_bps': mean_g,
            't_stat': t_g,
            'p_value': p_g,
            'ci_low': ci_g[0],
            'ci_high': ci_g[1],
            'net_taker_bps': mean_g - TAKER_COST,
            'net_maker_bps': mean_g - MAKER_COST,
            'sessions_positive': int(sess_pos),
            'total_sessions': len(by_sess),
            'frac_positive': (gross_a > 0).mean(),
        })
    
    # --- Hypothesis B: |imbalance_interaction| > threshold ---
    print("Evaluating Hypothesis B: Multi-Level Imbalance...")
    threshold_b = 0.3
    mask_b = (df_oos['imbalance_interaction'].abs() > threshold_b) & df_oos[f'r_{HORIZON}'].notna()
    if mask_b.sum() > 50:
        # Direction: sign of interaction
        gross_b = df_oos.loc[mask_b, f'r_{HORIZON}'].values * np.sign(df_oos.loc[mask_b, 'imbalance_interaction'].values)
        mean_g, t_g, p_g, ci_g = block_bootstrap_ci(gross_b)
        by_sess = df_oos.loc[mask_b].groupby('session').apply(
            lambda x: (x[f'r_{HORIZON}'] * np.sign(x['imbalance_interaction'])).mean()
        )
        sess_pos = (by_sess > 0).sum()
        
        results.append({
            'name': 'B: Multi-Level Imbalance',
            'feature': 'imbalance_interaction',
            'threshold': threshold_b,
            'n_signals': int(mask_b.sum()),
            'gross_bps': mean_g,
            't_stat': t_g,
            'p_value': p_g,
            'ci_low': ci_g[0],
            'ci_high': ci_g[1],
            'net_taker_bps': mean_g - TAKER_COST,
            'net_maker_bps': mean_g - MAKER_COST,
            'sessions_positive': int(sess_pos),
            'total_sessions': len(by_sess),
            'frac_positive': (gross_b > 0).mean(),
        })
    
    # --- Hypothesis C: size_weighted_tfi > threshold ---
    print("Evaluating Hypothesis C: Size-Weighted Flow...")
    threshold_c = df_oos['size_weighted_tfi'].quantile(0.7)
    mask_c = (df_oos['size_weighted_tfi'] > threshold_c) & df_oos[f'r_{HORIZON}'].notna()
    if mask_c.sum() > 50:
        gross_c = df_oos.loc[mask_c, f'r_{HORIZON}'].values
        mean_g, t_g, p_g, ci_g = block_bootstrap_ci(gross_c)
        by_sess = df_oos.loc[mask_c].groupby('session')[f'r_{HORIZON}'].mean()
        sess_pos = (by_sess > 0).sum()
        
        results.append({
            'name': 'C: Size-Weighted Flow',
            'feature': 'size_weighted_tfi',
            'threshold': threshold_c,
            'n_signals': int(mask_c.sum()),
            'gross_bps': mean_g,
            't_stat': t_g,
            'p_value': p_g,
            'ci_low': ci_g[0],
            'ci_high': ci_g[1],
            'net_taker_bps': mean_g - TAKER_COST,
            'net_maker_bps': mean_g - MAKER_COST,
            'sessions_positive': int(sess_pos),
            'total_sessions': len(by_sess),
            'frac_positive': (gross_c > 0).mean(),
        })
    
    # Print results
    print(f"\n{'='*70}")
    print("HYPOTHESIS EVALUATION RESULTS")
    print(f"{'='*70}")
    
    for r in results:
        print(f"\n{r['name']}")
        print(f"  Feature: {r['feature']}")
        print(f"  Threshold: {r['threshold']:.4f}")
        print(f"  Signals: {r['n_signals']}")
        print(f"  Gross: {r['gross_bps']:.6f} bps")
        print(f"  t-stat: {r['t_stat']:.4f}, p-value: {r['p_value']:.6f}")
        print(f"  95% CI: [{r['ci_low']:.6f}, {r['ci_high']:.6f}] bps")
        print(f"  Net (taker): {r['net_taker_bps']:.6f} bps")
        print(f"  Net (maker): {r['net_maker_bps']:.6f} bps")
        print(f"  Sessions positive: {r['sessions_positive']}/{r['total_sessions']}")
        print(f"  Fraction positive: {r['frac_positive']:.4f}")
        
        passes = (r['p_value'] < ALPHA and 
                  r['net_maker_bps'] > 0 and 
                  r['sessions_positive'] / r['total_sessions'] > 0.6)
        print(f"  Passes gate: {passes}")
    
    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY TABLE")
    print(f"{'='*70}")
    print(f"{'Hypothesis':<40} {'N':>6} {'Gross':>8} {'p-val':>8} {'Net(M)':>8} {'Pass':>6}")
    print(f"{'-'*70}")
    for r in results:
        passes = (r['p_value'] < ALPHA and 
                  r['net_maker_bps'] > 0 and 
                  r['sessions_positive'] / r['total_sessions'] > 0.6)
        print(f"{r['name']:<40} {r['n_signals']:>6} {r['gross_bps']:>8.4f} {r['p_value']:>8.4f} {r['net_maker_bps']:>8.4f} {'YES' if passes else 'NO':>6}")
    
    # Save
    results_df = pd.DataFrame(results)
    results_df.to_csv('data/research/oos_validation_results.csv', index=False)
    
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
        print("Classification: ECONOMICALLY INSUFFICIENT")
    print(f"{'='*70}")

if __name__ == "__main__":
    main()
