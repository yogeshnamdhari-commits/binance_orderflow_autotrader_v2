"""V6 execution simulation module."""

import numpy as np
import pandas as pd

from app.v3_labels import add_labels
from app.v6_features import compute_v6_features, get_v6_feature_names
from app.v5_cost import measured_gate

TAKER_COST = measured_gate()
MAKER_COST = 2.0
SLIPPAGE_BPS = 0.0079
LATENCY_COST_BPS = 0.05
FILL_PROB_MAKER = 0.70
HORIZON = 500


def simulate_full_execution(df, feature_name, horizon=HORIZON):
    """Full execution simulation with all cost components."""
    target_col = f'r_{horizon}'
    feature = df[feature_name]
    target = df[target_col]
    
    valid = feature.notna() & target.notna()
    if valid.sum() < 50:
        return None
    
    selected = df.loc[valid]
    signal = np.sign(selected[feature_name].values)
    gross = signal * selected[target_col].values
    
    # Cost breakdown
    taker_total = TAKER_COST
    maker_fee = MAKER_COST
    slippage = SLIPPAGE_BPS
    latency = LATENCY_COST_BPS
    
    # Adverse selection estimate (simplified: 0.5 bps for passive)
    adverse_selection = 0.5
    
    # Net calculations
    net_taker = gross - taker_total
    net_maker = gross - maker_fee - slippage - latency - adverse_selection
    
    # Expected net with fill probability
    expected_net_maker = FILL_PROB_MAKER * net_maker
    
    return {
        'feature': feature_name,
        'n_signals': int(valid.sum()),
        'gross_bps': float(np.mean(gross)),
        'net_taker_bps': float(np.mean(net_taker)),
        'net_maker_bps': float(np.mean(net_maker)),
        'expected_net_maker_bps': float(np.mean(expected_net_maker)),
        'break_even_cost': float(np.mean(gross)),
        'cost_breakdown': {
            'taker_fee': 4.0,
            'maker_fee': 2.0,
            'slippage': slippage,
            'latency': latency,
            'adverse_selection': adverse_selection,
            'total_maker': maker_fee + slippage + latency + adverse_selection,
        },
        'max_adverse': float(np.min(gross)),
        'max_favorable': float(np.max(gross)),
        'std': float(np.std(gross)),
        'frac_positive': float((gross > 0).mean()),
    }


def run_v6_execution(data_path='data/research/v5_evidence_features.parquet'):
    """Run full V6 execution simulation."""
    print("=" * 70)
    print("V6 EXECUTION SIMULATION")
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
    
    results = []
    for feat in get_v6_feature_names():
        r = simulate_full_execution(df_oos, feat, HORIZON)
        if r:
            results.append(r)
            
            print(f"{feat}:")
            print(f"  Gross: {r['gross_bps']:.4f} bps")
            print(f"  Net (taker): {r['net_taker_bps']:.4f} bps")
            print(f"  Net (maker): {r['net_maker_bps']:.4f} bps")
            print(f"  Expected net (maker, 70% fill): {r['expected_net_maker_bps']:.4f} bps")
            print(f"  Break-even cost: {r['break_even_cost']:.4f} bps")
            print(f"  Max adverse: {r['max_adverse']:.4f} bps")
            print(f"  Max favorable: {r['max_favorable']:.4f} bps")
            print(f"  Fraction positive: {r['frac_positive']:.4f}")
            print()
    
    # Save
    if results:
        results_df = pd.DataFrame(results)
        results_df.to_csv('data/research/v6_execution_results.csv', index=False)
        print(f"Saved to data/research/v6_execution_results.csv")
    
    return results


if __name__ == '__main__':
    run_v6_execution()
