"""V6 research engine — OOS validation module.

Validates V6 features against frozen V5 baseline using chronological OOS.
"""

import numpy as np
import pandas as pd
from scipy import stats as scs

from app.v3_labels import add_labels
from app.v6_features import compute_v6_features, get_v6_feature_names
from app.v5_cost import measured_gate

TAKER_COST = measured_gate()
MAKER_COST = 2.0
ALPHA = 0.05 / 7  # Bonferroni for 7 hypotheses
HORIZON = 500


def block_bootstrap_ci(values, block_size=50, n_boot=2000, alpha=0.05, seed=42):
    """Moving-block bootstrap confidence interval."""
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


def evaluate_feature(df_oos, feature_name, horizon=500):
    """Evaluate a single V6 feature on OOS data.
    
    Tests whether the feature has predictive power for future returns.
    Uses sign of feature as direction signal.
    """
    target_col = f'r_{horizon}'
    if feature_name not in df_oos.columns or target_col not in df_oos.columns:
        return None
    
    feature = df_oos[feature_name]
    target = df_oos[target_col]
    
    # Valid data
    valid = feature.notna() & target.notna()
    if valid.sum() < 50:
        return None
    
    selected = df_oos.loc[valid]
    feature_vals = selected[feature_name].values
    target_vals = selected[target_col].values
    
    # Signal direction: sign of feature
    signal = np.sign(feature_vals)
    gross = signal * target_vals
    
    mean_g, t_g, p_g, ci_g = block_bootstrap_ci(gross)
    net_taker = mean_g - TAKER_COST
    net_maker = mean_g - MAKER_COST
    
    # Per-session analysis
    by_session = selected.groupby('session').apply(
        lambda x: (np.sign(x[feature_name]) * x[target_col]).mean()
    )
    sessions_positive = (by_session > 0).sum()
    
    # Permutation control (shuffle directions within sessions)
    perm_gross_list = []
    rng = np.random.RandomState(42)
    for _ in range(100):
        perm_signal = signal.copy()
        for sess in selected['session'].unique():
            mask = selected['session'].values == sess
            perm_signal[mask] = rng.permutation(perm_signal[mask])
        perm_gross = perm_signal * target_vals
        perm_gross_list.append(np.mean(perm_gross))
    perm_mean = np.mean(perm_gross_list)
    
    return {
        'feature': feature_name,
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
        'perm_mean_bps': perm_mean,
    }


def run_v6_research(data_path='data/research/v5_evidence_features.parquet'):
    """Run complete V6 OOS validation."""
    print("=" * 70)
    print("V6 RESEARCH: OOS VALIDATION")
    print("=" * 70)
    print(f"Bonferroni-corrected α = {ALPHA:.5f}")
    print(f"Horizon: {HORIZON}ms")
    print()
    
    # Load data
    df = pd.read_parquet(data_path)
    df = add_labels(df, (HORIZON,))
    
    # Compute V6 features
    print("Computing V6 features...")
    df = compute_v6_features(df)
    
    # Chronological split
    sessions = sorted(df['session'].unique())
    n_train = int(len(sessions) * 0.6)
    oos_sessions = sessions[n_train:]
    df_oos = df[df['session'].isin(oos_sessions)].copy()
    
    print(f"Total sessions: {len(sessions)}")
    print(f"OOS sessions: {len(oos_sessions)}")
    print(f"OOS events: {len(df_oos)}")
    print()
    
    # Evaluate each V6 feature
    results = []
    for feat in get_v6_feature_names():
        r = evaluate_feature(df_oos, feat, HORIZON)
        if r:
            results.append(r)
    
    # Print results
    print(f"\n{'='*70}")
    print("V6 FEATURE EVALUATION RESULTS")
    print(f"{'='*70}")
    
    for r in results:
        print(f"\n{r['feature']}")
        print(f"  Signals: {r['n_signals']}")
        print(f"  Gross: {r['gross_bps']:.6f} bps")
        print(f"  t-stat: {r['t_stat']:.4f}, p-value: {r['p_value']:.6f}")
        print(f"  95% CI: [{r['ci_low']:.6f}, {r['ci_high']:.6f}] bps")
        print(f"  Net (taker): {r['net_taker_bps']:.6f} bps")
        print(f"  Net (maker): {r['net_maker_bps']:.6f} bps")
        print(f"  Sessions positive: {r['sessions_positive']}/{r['total_sessions']}")
        print(f"  Permutation mean: {r['perm_mean_bps']:.6f} bps")
        
        passes = (r['p_value'] < ALPHA and 
                  r['net_maker_bps'] > 0 and 
                  r['sessions_positive'] / r['total_sessions'] > 0.6)
        print(f"  Passes gate: {passes}")
    
    # Summary table
    print(f"\n{'='*70}")
    print("SUMMARY TABLE")
    print(f"{'='*70}")
    print(f"{'Feature':<25} {'N':>6} {'Gross':>8} {'p-val':>8} {'Net(M)':>8} {'Pass':>6}")
    print(f"{'-'*60}")
    for r in results:
        passes = (r['p_value'] < ALPHA and 
                  r['net_maker_bps'] > 0 and 
                  r['sessions_positive'] / r['total_sessions'] > 0.6)
        print(f"{r['feature']:<25} {r['n_signals']:>6} {r['gross_bps']:>8.4f} {r['p_value']:>8.4f} {r['net_maker_bps']:>8.4f} {'YES' if passes else 'NO':>6}")
    
    # Save results
    results_df = pd.DataFrame(results)
    results_df.to_csv('data/research/v6_feature_results.csv', index=False)
    print(f"\nSaved to data/research/v6_feature_results.csv")
    
    return results


if __name__ == '__main__':
    run_v6_research()
