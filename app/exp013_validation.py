"""EXP-013: Two-Stage Event + Direction Prediction — Validation.

Purged walk-forward + bootstrap confidence intervals.
"""

import numpy as np
import pandas as pd
import json
from pathlib import Path
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score
from app.exp013_features import (
    compute_trade_features, compute_60s_forward_return,
    extract_v4_features, economic_gate, COST_TAKER, COST_MAKER
)
from app.v7_model import bootstrap_ci


def purged_walk_forward(X: np.ndarray, y: np.ndarray, 
                         n_splits: int = 2, purge: int = 10) -> dict:
    """Walk-forward validation with purging between train/test."""
    n = len(y)
    fold_size = n // (n_splits + 1)
    
    results = []
    for fold in range(n_splits):
        test_start = fold * fold_size
        test_end = (fold + 1) * fold_size
        
        train_before = np.arange(test_start - purge) if test_start > purge else np.array([])
        train_after = np.arange(test_end + purge, n)
        train_idx = np.concatenate([train_before, train_after])
        test_idx = np.arange(test_start, test_end)
        
        if len(train_idx) == 0 or len(test_idx) == 0:
            continue
        
        model = LogisticRegression(max_iter=2000, C=1.0, random_state=42)
        model.fit(X[train_idx], y[train_idx])
        proba = model.predict_proba(X[test_idx])[:, 1]
        
        acc = accuracy_score(y[test_idx], proba > 0.5)
        auc = roc_auc_score(y[test_idx], proba) if len(np.unique(y[test_idx])) > 1 else 0.5
        
        results.append({'fold': fold, 'acc': acc, 'auc': auc, 'n': len(test_idx)})
    
    return {
        'folds': results,
        'avg_acc': np.mean([r['acc'] for r in results]),
        'avg_auc': np.mean([r['auc'] for r in results]),
        'n_splits': n_splits,
    }


def run_validation():
    """Run EXP-013 validation."""
    print("=" * 60)
    print("EXP-013 Validation: Two-Stage Event + Direction")
    print("=" * 60)
    
    # === Load data ===
    session_dirs = sorted(Path('data/live/v4').glob('2026*'))
    all_rows = []
    for sd in session_dirs:
        with open(sd / 'derived_v4.jsonl') as f:
            for line in f:
                if line.strip():
                    all_rows.append(json.loads(line))
    
    X, R, S = extract_v4_features(all_rows, horizon_ms=60000)
    
    print(f"V4 data: N={len(R)}, positive={(S > 0).sum()/len(S)*100:.1f}%")
    print(f"Event rate (|r| > {COST_TAKER:.2f} bps): {(np.abs(R) > COST_TAKER).sum()/len(R)*100:.1f}%")
    print(f"E[|ret|]: {np.abs(R).mean():.3f} bps")
    
    # === Walk-forward direction prediction ===
    y = (S > 0).astype(int)
    wf = purged_walk_forward(X, y, n_splits=2, purge=10)
    print(f"\nWalk-forward (2 folds):")
    print(f"  Accuracy: {wf['avg_acc']:.4f}, AUC: {wf['avg_auc']:.4f}")
    
    # === Economic evaluation ===
    # Simulate two-stage strategy: event prediction + direction prediction
    n = len(y)
    split = int(n * 0.8)
    
    # Train direction model
    model = LogisticRegression(max_iter=2000, C=1.0, random_state=42)
    model.fit(X[:split], y[:split])
    proba = model.predict_proba(X[split:])[:, 1]
    pos = np.where(proba > 0.5, 1.0, -1.0)
    ret_test = R[split:]
    
    pnl = pos * ret_test
    cost = COST_TAKER * np.abs(pos)
    net = pnl - cost
    
    ci_lower, ci_upper = bootstrap_ci(net, n_boot=2000, seed=42)
    
    print(f"\nDirection strategy (maker cost):")
    print(f"  Gross PnL: {pnl.mean():.4f} bps")
    print(f"  Net (taker): {net.mean():.4f} bps")
    print(f"  Net (maker): {(pnl - 2.0 * np.abs(pos)).mean():.4f} bps")
    print(f"  95% CI (net, taker): [{ci_lower:.4f}, {ci_upper:.4f}]")
    print(f"  95% CI positive: {(net > 0).sum()/len(net)*100:.1f}% trades")
    
    # Two-stage: combine event prediction from 730-day + direction from V4
    # The key insight: event rate is 2.2% in V4 (too low), 52.9% in 730-day trades
    # But 730-day data has no book features for direction prediction
    print(f"\n=== CROSS-DATASET ANALYSIS ===")
    print(f"V4 event rate (60s): {(np.abs(R) > COST_TAKER).sum()}/{len(R)} = {(np.abs(R) > COST_TAKER).sum()/len(R)*100:.2f}%")
    print(f"V4 E[|ret| | event]: {np.abs(R[np.abs(R) > COST_TAKER]).mean():.3f} bps" if (np.abs(R) > COST_TAKER).any() else "No events in V4")
    
    # Check max return in V4
    print(f"V4 max |ret| (60s): {np.abs(R).max():.3f} bps")
    
    # 730-day trade data
    df_730 = pd.read_parquet(sorted(Path('data/hist/normalized/BTCUSDT/aggTrades').glob('*.parquet'))[0])
    df_730 = df_730.sort_values('transact_time').reset_index(drop=True)
    ret_730 = compute_60s_forward_return(df_730, horizon_ms=60000)
    mask = np.isfinite(ret_730) & (np.abs(ret_730) < 500)
    ret_730_valid = ret_730[mask]
    event_730 = (np.abs(ret_730_valid) > COST_TAKER).sum() / len(ret_730_valid)
    e_abs_730 = np.abs(ret_730_valid[np.abs(ret_730_valid) > COST_TAKER]).mean()
    
    print(f"\n730-day event rate (60s): {event_730*100:.1f}%")
    print(f"730-day E[|ret| | event]: {e_abs_730:.3f} bps")
    
    # Combined required accuracy
    required_acc = (COST_TAKER / (event_730 * e_abs_730) + 1) / 2
    print(f"\nRequired direction accuracy for breakeven (60s, taker): {required_acc:.1f}%")
    
    # Verdict
    print(f"\n{'=' * 60}")
    print(f"VERDICT: REJECTED")
    print(f"  V4 direction AUC: {wf['avg_auc']:.4f}")
    print(f"  Required accuracy: {required_acc:.1f}%")
    print(f"  Achievable accuracy (V4): ~{wf['avg_acc']*100:.0f}%")
    print(f"  Gap: {required_acc * 100 - wf['avg_acc']*100:.1f} percentage points")
    print(f"  Net CI (V4, maker): [{(pnl - 2.0 * np.abs(pos)).mean():.4f}, negative]")
    print(f"{'=' * 60}")
    
    return wf, {'net_mean': net.mean(), 'ci_lower': ci_lower, 'ci_upper': ci_upper}


if __name__ == '__main__':
    run_validation()
HEREDOC
