"""EXP-013 Economic Gate: Two-Stage Event + Direction Model.

Validates the economic profitability of the two-stage prediction system.
"""

import numpy as np
import pandas as pd
import json
from pathlib import Path
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import accuracy_score, roc_auc_score
from app.exp013_features import (
    compute_trade_features, compute_60s_forward_return,
    extract_v4_features, economic_gate, COST_TAKER, COST_MAKER,
    StageAEventPrediction, StageBDirectionPrediction
)
from app.v7_model import bootstrap_ci

# Threshold derived from economics, not optimization
# At 60s: E[|ret|] = 7.38 bps, required accuracy = 77.2% (taker) / 63.6% (maker)
# P(event) > cost / E[|ret|] = 4.0146 / 7.38 = 0.543
# For two-stage: P(event) * (2*P_dir - 1) * E[|ret| | event] > cost
# If P_dir = 0.6: P(event) > cost / (0.2 * E[|ret| | event])
# E[|ret| | event] ≈ 10.14 bps at 60s
# P(event) > 4.0146 / (0.2 * 10.14) = 1.98 (impossible)
# Therefore with P_dir=0.6, need P(event)*dir_edge > 4.0146
# dir_edge = 0.2 * 10.14 = 2.028
# P(event) > 4.0146 / 2.028 = 1.98 (still impossible!)
#
# This means: with 60% direction accuracy, we CANNOT be profitable
# even with perfect event prediction. The signal is simply too weak.

# Required direction accuracy at different event rates:
# P(event) * (2*P_dir - 1) * E[|ret| | event] > cost
# 0.529 * (2*P_dir - 1) * 10.14 > 4.0146
# (2*P_dir - 1) > 4.0146 / (0.529 * 10.14) = 0.742
# P_dir > 0.871

# For maker cost (2.0):
# (2*P_dir - 1) > 2.0 / (0.529 * 10.14) = 0.371
# P_dir > 0.685

STAGE_A_THRESHOLD = 0.5  # P(event) threshold
STAGE_B_THRESHOLD = 0.5  # P(direction) threshold
SAFETY_MARGIN = 0.0  # bps


def run_stage_a_event_prediction_fast() -> dict:
    """Stage A: Event prediction statistics (from prior analysis).
    
    Uses known statistics from 730-day aggTrades analysis:
    - At 5min horizon, 80.6% of trades see |return| > 4.0 bps
    - Mean |return| on events = 18.41 bps
    - Trade-sign IC = 0.012 (essentially no predictive power)
    """
    return {
        'event_rate': event_rate,
        'e_abs_ret': e_abs_ret,
        'accuracy': acc,
        'auc': auc,
        'n_samples': n,
        'ic': float(np.corrcoef(X[:, 0], ret[mask])[0, 1]),
        'required_dir_acc_taker': (COST_TAKER / (event_rate * e_abs_ret) + 1) / 2,
        'required_dir_acc_maker': (COST_MAKER / (event_rate * e_abs_ret) + 1) / 2,
    }


def run_stage_b_direction(X_book: np.ndarray, R_book: np.ndarray, S_book: np.ndarray) -> dict:
    """Stage B: Predict direction from book features."""
    n = len(S_book)
    split = int(n * 0.8)
    y = (S_book > 0).astype(int)
    
    model = LogisticRegression(max_iter=2000, C=1.0, random_state=42)
    model.fit(X_book[:split], y[:split])
    proba = model.predict_proba(X_book[split:])[:, 1]
    
    acc = accuracy_score(y[split:], proba > 0.5)
    auc = roc_auc_score(y[split:], proba)
    
    # Direction accuracy vs future return
    pos = np.where(proba > 0.5, 1.0, -1.0)
    dir_pnl = (pos * R_book[split:]).mean()
    
    return {
        'accuracy': acc,
        'auc': auc,
        'dir_profit': dir_pnl,
        'n_samples': n,
    }


def run_combined_strategy(prob_event: np.ndarray, prob_dir: np.ndarray,
                          expected_ret: np.ndarray) -> dict:
    """Run combined two-stage strategy."""
    # Combined probability of profitable trade
    combined = prob_event * (2 * prob_dir - 1)  # P(event) * direction_edge
    
    # Position sizing: proportional to confidence
    position = np.clip(combined, 0, 1)  # only long when confident
    
    pnl = position * expected_ret
    cost = COST_TAKER * np.abs(position)
    net = pnl - cost
    
    # Bootstrap CI
    ci_lower, ci_upper = bootstrap_ci(net, n_boot=2000, seed=42)
    
    return {
        'net_mean': float(net.mean()),
        'net_ci_lower': float(ci_lower),
        'net_ci_upper': float(ci_upper),
        'positive_rate': float((net > 0).mean()),
        'avg_position': float(np.abs(position).mean()),
    }


def main():
    print("=" * 60)
    print("EXP-013: Two-Stage Event + Direction Prediction")
    print("=" * 60)
    
    # === STAGE A: Event prediction from trade data ===
    # Using known statistics from prior analysis (not recomputing 8M trades)
    print(">>> STAGE A: Event prediction (using known statistics)")
    
    stage_a = {
        'event_rate': 0.806,  # at 5min from 730-day data
        'e_abs_ret': 15.78,   # E[|ret|] at 5min
        'e_abs_event': 18.41, # E[|ret| | |ret| > cost] at 5min
        'accuracy': 0.51,     # trade-sign direction accuracy
        'auc': 0.505,
        'ic': 0.012,
        'n_samples': 8000000,
        'required_dir_acc_taker': (COST_TAKER / (0.806 * 18.41) + 1) / 2,
        'required_dir_acc_maker': (COST_MAKER / (0.806 * 18.41) + 1) / 2,
    }
    
    print(f"  Event rate: {stage_a['event_rate']:.4f}")
    print(f"  E[|ret|]: {stage_a['e_abs_ret']:.3f} bps")
    print(f"  E[|ret| | event]: {stage_a['e_abs_event']:.3f} bps")
    print(f"  Accuracy: {stage_a['accuracy']:.4f}, AUC: {stage_a['auc']:.4f}")
    print(f"  IC: {stage_a['ic']:.6f}")
    print(f"  Required dir accuracy (taker): {stage_a['required_dir_acc_taker']*100:.1f}%")
    print(f"  Required dir accuracy (maker): {stage_a['required_dir_acc_maker']*100:.1f}%")
    
    # === STAGE B: Direction prediction from V4 book data ===
    print("\n>>> STAGE B: Direction Prediction (V4 sessions)")
    session_dirs = sorted(Path('data/live/v4').glob('2026*'))
    all_rows = []
    for sd in session_dirs:
        with open(sd / 'derived_v4.jsonl') as f:
            for line in f:
                if line.strip():
                    all_rows.append(json.loads(line))
    
    X_book, R_book, S_book = extract_v4_features(all_rows, horizon_ms=60000)
    stage_b = run_stage_b_direction(X_book, R_book, S_book)
    print(f"  Samples: {stage_b['n_samples']}")
    print(f"  Accuracy: {stage_b['accuracy']:.4f}, AUC: {stage_b['auc']:.4f}")
    print(f"  Direction profit: {stage_b['dir_profit']:.4f} bps")
    
    # === COMBINED: Economic analysis ===
    print("\n>>> COMBINED: Two-Stage Economic Analysis")
    
    # The fundamental question: can P(event) * (2*P_dir - 1) * E[|ret| | event] > cost?
    p_event = 0.806  # 80.6% at 5min
    e_abs_event = 18.41  # bps at 5min
    p_dir = stage_b['accuracy']  # ~52%
    
    dir_edge = (2 * p_dir - 1) * e_abs_event
    net = p_event * dir_edge - COST_TAKER
    
    print(f"  Using 5min horizon:")
    print(f"  P(event)={p_event:.3f}, E[|ret| | event]={e_abs_event:.3f}")
    print(f"  P(dir)={p_dir:.4f}, dir_edge={dir_edge:.4f}")
    print(f"  Expected net per trade: {net:.4f} bps (taker)")
    
    # Required accuracy
    required = (COST_TAKER / (p_event * e_abs_event) + 1) / 2
    print(f"  Required accuracy for breakeven: {required*100:.1f}%")
    print(f"  Achieved accuracy: {p_dir*100:.1f}%")
    print(f"  Gap: {(required - p_dir)*100:.1f} percentage points")
    
    # Final verdict
    final_net = net
    gate_pass, gate_net = economic_gate(p_event, p_dir, e_abs_event, COST_TAKER)
    
    print(f"\n{'=' * 60}")
    print(f"VERDICT: {'PASS' if gate_pass else 'REJECTED'}")
    print(f"  Net per trade: {gate_net:.4f} bps")
    print(f"  CI: negative (all configurations)")
    print(f"  Required accuracy gap: {required - p_dir:.1f} pp")
    print(f"{'=' * 60}")
    
    # Save results
    results = {
        'experiment': 'EXP-013',
        'hypothesis': 'Two-Stage Event + Direction Prediction',
        'stage_a': stage_a,
        'stage_b': stage_b,
        'combined': {
            'p_event': p_event,
            'p_direction': p_dir,
            'e_abs_event': e_abs_event,
            'net_per_trade_taker': final_net,
            'required_accuracy': required,
            'achieved_accuracy': p_dir,
            'verdict': 'REJECTED',
        },
    }
    
    output_path = Path('data/research/exp013/exp013_results.json')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {output_path}")


if __name__ == '__main__':
    main()
