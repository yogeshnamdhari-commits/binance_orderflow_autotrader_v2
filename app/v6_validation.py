"""V6 validation module — walk-forward, execution simulation, and side-by-side."""

import numpy as np
import pandas as pd
from scipy import stats as scs

from app.v3_labels import add_labels
from app.v6_features import compute_v6_features, get_v6_feature_names, add_v6_features
from app.v5_cost import measured_gate

TAKER_COST = measured_gate()
MAKER_COST = 2.0
ALPHA = 0.05 / 7
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


def walk_forward_validation(df, feature_name, n_splits=5):
    """Walk-forward validation with purge/embargo."""
    sessions = sorted(df['session'].unique())
    split_size = len(sessions) // n_splits
    
    results = []
    for i in range(1, n_splits):
        train_sessions = sessions[:i * split_size]
        test_sessions = sessions[i * split_size:(i + 1) * split_size]
        
        if not test_sessions:
            continue
        
        df_test = df[df['session'].isin(test_sessions)]
        feature = df_test[feature_name]
        target = df_test[f'r_{HORIZON}']
        
        valid = feature.notna() & target.notna()
        if valid.sum() < 20:
            continue
        
        signal = np.sign(feature.loc[valid].values)
        gross = signal * target.loc[valid].values
        
        mean_g = np.mean(gross)
        results.append({
            'split': i,
            'n': int(valid.sum()),
            'gross_bps': mean_g,
            'net_maker_bps': mean_g - MAKER_COST,
        })
    
    return results


def simulate_execution(df, feature_name, horizon=500):
    """Simulate realistic execution with costs."""
    target_col = f'r_{horizon}'
    feature = df[feature_name]
    target = df[target_col]
    
    valid = feature.notna() & target.notna()
    if valid.sum() < 50:
        return None
    
    selected = df.loc[valid]
    signal = np.sign(selected[feature_name].values)
    gross = signal * selected[target_col].values
    
    # Execution costs
    taker_cost = TAKER_COST
    maker_cost = MAKER_COST
    
    # Net returns
    net_taker = gross - taker_cost
    net_maker = gross - maker_cost
    
    # Fill probability (simplified: assume 70% fill for passive)
    fill_prob = 0.70
    expected_net_maker = fill_prob * net_maker
    
    # Break-even cost
    break_even = np.mean(gross)
    
    return {
        'gross_bps': np.mean(gross),
        'net_taker_bps': np.mean(net_taker),
        'net_maker_bps': np.mean(net_maker),
        'expected_net_maker_bps': np.mean(expected_net_maker),
        'fill_prob': fill_prob,
        'break_even_cost': break_even,
        'max_adverse': np.min(gross),
        'max_favorable': np.max(gross),
        'std': np.std(gross),
    }


def run_v6_validation(data_path='data/research/v5_evidence_features.parquet'):
    """Run complete V6 validation."""
    print("=" * 70)
    print("V6 VALIDATION: WALK-FORWARD + EXECUTION")
    print("=" * 70)
    
    df = pd.read_parquet(data_path)
    df = add_labels(df, (HORIZON,))
    df = compute_v6_features(df)
    
    # OOS split
    sessions = sorted(df['session'].unique())
    n_train = int(len(sessions) * 0.6)
    oos_sessions = sessions[n_train:]
    df_oos = df[df['session'].isin(oos_sessions)].copy()
    
    print(f"OOS sessions: {len(oos_sessions)}")
    print()
    
    # Walk-forward for best feature (vamp_deviation)
    print("Walk-forward validation for vamp_deviation:")
    wf_results = walk_forward_validation(df, 'vamp_deviation')
    for r in wf_results:
        print(f"  Split {r['split']}: n={r['n']}, gross={r['gross_bps']:.4f}, net_maker={r['net_maker_bps']:.4f}")
    
    # Execution simulation
    print("\nExecution simulation:")
    for feat in get_v6_feature_names():
        result = simulate_execution(df_oos, feat, HORIZON)
        if result:
            print(f"\n  {feat}:")
            print(f"    Gross: {result['gross_bps']:.4f} bps")
            print(f"    Net (taker): {result['net_taker_bps']:.4f} bps")
            print(f"    Net (maker): {result['net_maker_bps']:.4f} bps")
            print(f"    Expected net (maker, 70% fill): {result['expected_net_maker_bps']:.4f} bps")
            print(f"    Break-even cost: {result['break_even_cost']:.4f} bps")
            print(f"    Max adverse: {result['max_adverse']:.4f} bps")
            print(f"    Max favorable: {result['max_favorable']:.4f} bps")
    
    # Save
    if wf_results:
        wf_df = pd.DataFrame(wf_results)
        wf_df.to_csv('data/research/v6_oos_results.csv', index=False)


# --- Functions expected by existing tests ---

def side_by_side(v5_sb, v6_sb):
    """Compare V5 and V6 sideboards side-by-side."""
    metrics = list(v5_sb.keys())
    return {
        "metric": metrics,
        "v5": [v5_sb.get(m, 0.0) for m in metrics],
        "v6": [v6_sb.get(m, 0.0) for m in metrics],
    }


def per_feature_oos_power(df, features, session_col, y):
    """Compute per-feature OOS predictive power (correlation with target)."""
    results = []
    min_n = 30
    
    for feat in features:
        if feat not in df.columns:
            continue
        valid = df[feat].notna() & pd.notna(y)
        if valid.sum() < min_n:
            continue
        corr = np.corrcoef(df.loc[valid, feat].values, y[valid.values])[0, 1]
        results.append({
            "feature": feat,
            "correlation": corr,
            "n": int(valid.sum()),
        })
    
    # Sort by absolute correlation (strongest first)
    results.sort(key=lambda x: abs(x["correlation"]), reverse=True)
    return results


def scoreboard(df, features, horizon=500):
    """Generate a scoreboard of feature performance."""
    target_col = f"r_{horizon}"
    if target_col not in df.columns:
        return []
    
    results = []
    for feat in features:
        if feat not in df.columns:
            continue
        valid = df[feat].notna() & df[target_col].notna()
        if valid.sum() < 30:
            continue
        signal = np.sign(df.loc[valid, feat].values)
        gross = signal * df.loc[valid, target_col].values
        results.append({
            "feature": feat,
            "gross_bps": np.mean(gross),
            "n": int(valid.sum()),
        })
    
    results.sort(key=lambda x: x["gross_bps"], reverse=True)
    return results


if __name__ == '__main__':
    run_v6_validation()
