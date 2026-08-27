"""V8 research engine — OOS validation with economic gate.

Tests whether V8 trade-flow microstructure features provide economically viable
predictive signal using the full 730-day aggTrades dataset.

Pipeline:
1. Compute V8 features from sampled aggTrades (5000 trades/day)
2. Add causal forward return labels (no look-ahead)
3. Chronological 70/15/15 split by timestamp
4. Size threshold p99.9 computed on train slice ONLY
5. Evaluate each feature on OOS using sign-based signal
6. Economic gate: maker cost 2.0 bps + safety margin 0.5 bps
7. Walk-forward validation (5 windows)
8. Permutation control
9. Bonferroni correction (12 features, α = 0.05/12)
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional
from scipy import stats as scs

from app.v8_features import V8_FEATURES, compute_v8_features_aggtrades, add_causal_labels


# Economic gate parameters (frozen, from v5_cost / v3_cost)
MAKER_FEE_BPS = 2.0
SAFETY_MARGIN_BPS = 0.5
MAKER_GATE_BPS = MAKER_FEE_BPS + SAFETY_MARGIN_BPS  # 2.5 bps
TAKER_GATE_BPS = 4.0146 + SAFETY_MARGIN_BPS  # ~4.5 bps

# Bonferroni correction: 12 features tested
ALPHA = 0.05 / 12
HORIZON_MS = 500

SPLIT_FRACTIONS = (0.70, 0.15, 0.15)  # chronological


def chronological_split(ts_ms: np.ndarray, fractions=SPLIT_FRACTIONS):
    """Create chronological train/val/oos masks based on timestamp quantiles."""
    cut1 = np.quantile(ts_ms, fractions[0])
    cut2 = np.quantile(ts_ms, fractions[0] + fractions[1])
    train_mask = ts_ms <= cut1
    val_mask = (ts_ms > cut1) & (ts_ms <= cut2)
    oos_mask = ts_ms > cut2
    return train_mask, val_mask, oos_mask


def block_bootstrap_ci(values: np.ndarray, block_size: int = 100,
                       n_boot: int = 2000, alpha: float = 0.05,
                       seed: int = 42) -> Tuple[float, float, float, float]:
    """Moving-block bootstrap CI for mean.

    Block size in samples (~100 trades ≈ 1s at typical 100tps rate).
    """
    values = values[np.isfinite(values)]
    n = len(values)
    if n == 0:
        return 0.0, 0.0, 1.0, (0.0, 0.0)
    if n < 10:
        mean = float(np.mean(values))
        se = float(np.std(values, ddof=1) / np.sqrt(n)) if n > 1 else 0.0
        t = mean / se if se > 0 else 0.0
        p = 2 * (1 - float(scs.t.cdf(abs(t), n - 1))) if n > 1 else 1.0
        return mean, t, p, (mean - 1.96 * se, mean + 1.96 * se)

    rng = np.random.RandomState(seed)
    n_blocks = max(1, int(np.ceil(n / block_size)))
    boot_means = np.empty(n_boot)
    for i in range(n_boot):
        starts = rng.randint(0, n, size=n_blocks)
        sample = np.concatenate([values[s:s + block_size] for s in starts])[:n]
        boot_means[i] = np.mean(sample)

    mean = float(np.mean(values))
    lo = float(np.percentile(boot_means, 100 * alpha / 2))
    hi = float(np.percentile(boot_means, 100 * (1 - alpha / 2)))

    if n > 1:
        se = float(np.std(values, ddof=1) / np.sqrt(n))
        t = mean / se if se > 0 else 0.0
        p = 2 * (1 - float(scs.t.cdf(abs(t), n - 1)))
    else:
        t, p = 0.0, 1.0

    return mean, t, p, (lo, hi)


def evaluate_v8_feature(df_oos: pd.DataFrame, feature: str,
                        horizon: int = HORIZON_MS) -> Optional[Dict]:
    """Evaluate a single V8 feature on OOS data.

    Tests: does sign(feature) predict direction of future return?
    Uses sign-based directional signal (no threshold optimization).
    """
    label_col = f'r_{horizon}'
    if feature not in df_oos.columns or label_col not in df_oos.columns:
        return None

    feature_vals = df_oos[feature].to_numpy(float)
    target = df_oos[label_col].to_numpy(float)
    dates = df_oos['date'].values

    # Handle extreme outliers: clip to 99th/1st percentile
    finite_mask = np.isfinite(feature_vals) & np.isfinite(target)
    if finite_mask.sum() < 50:
        return None

    valid_feature = feature_vals[finite_mask]
    valid_target = target[finite_mask]
    valid_dates = dates[finite_mask]

    q_lo = np.percentile(valid_feature, 1)
    q_hi = np.percentile(valid_feature, 99)
    clipped = np.clip(valid_feature, q_lo, q_hi)

    # Sign-based signal
    signal = np.sign(clipped)
    gross = signal * valid_target

    gross_mean, gross_t, gross_p, gross_ci = block_bootstrap_ci(gross, block_size=100)

    net_maker = gross_mean - MAKER_GATE_BPS
    net_taker = gross_mean - TAKER_GATE_BPS

    # Per-date analysis
    date_positive = 0
    date_stats = []
    for dt in np.unique(valid_dates):
        mask = valid_dates == dt
        if mask.sum() >= 10:
            d_gross = np.mean(gross[mask])
            if d_gross > 0:
                date_positive += 1
            date_stats.append(d_gross)

    dates_total = len(np.unique(valid_dates))

    # Permutation control: 20 permutations
    rng = np.random.RandomState(42)
    perm_means = []
    for i in range(20):
        perm_signal = rng.permutation(signal)
        perm_gross = perm_signal * valid_target
        perm_means.append(np.mean(perm_gross))
    perm_mean = float(np.mean(perm_means))
    perm_ci = (float(np.percentile(perm_means, 2.5)), float(np.percentile(perm_means, 97.5)))

    return {
        'feature': feature,
        'n_signals': int(finite_mask.sum()),
        'gross_bps': float(gross_mean),
        'gross_t_stat': float(gross_t),
        'gross_p_value': float(gross_p),
        'gross_ci95_low': float(gross_ci[0]),
        'gross_ci95_high': float(gross_ci[1]),
        'net_maker_bps': float(net_maker),
        'net_taker_bps': float(net_taker),
        'dates_positive': int(date_positive),
        'total_dates': int(dates_total),
        'perm_mean_bps': perm_mean,
        'perm_ci95_low': perm_ci[0],
        'perm_ci95_high': perm_ci[1],
        'incremental_vs_perm': float(gross_mean - perm_mean),
        'fraction_positive': float((gross > 0).mean()),
    }


def run_walk_forward_v8(df: pd.DataFrame, features: List[str],
                        horizon_ms: int, verbose: bool = True) -> List[Dict]:
    """Run walk-forward validation with 5 chronological windows."""
    df = df.sort_values('ts_ms').reset_index(drop=True)
    ts = df['ts_ms'].to_numpy(dtype=np.int64)
    label_col = f'r_{horizon_ms}'
    y = df[label_col].to_numpy(float)

    n_windows = 5
    min_train_frac = 0.3
    results = []

    for w in range(n_windows):
        cut_frac = min_train_frac + (1 - min_train_frac) * w / max(n_windows - 1, 1)
        test_frac = (1 - cut_frac) / 2

        cut_train = np.quantile(ts, cut_frac)
        cut_test = np.quantile(ts, cut_frac + test_frac)

        train_mask = ts <= cut_train
        test_mask = (ts > cut_train) & (ts <= cut_test)

        if train_mask.sum() < 500 or test_mask.sum() < 50:
            results.append({'window': w, 'error': 'insufficient data'})
            continue

        window_results = {'window': w, 'n_train': int(train_mask.sum()),
                          'n_test': int(test_mask.sum()), 'features': {}}

        for feat in features:
            if feat not in df.columns or label_col not in df.columns:
                continue

            X = df[feat].to_numpy(float)
            finite = np.isfinite(X) & np.isfinite(y)
            if finite.sum() < 50:
                continue

            # Clip using train quantiles
            train_finite = finite & train_mask
            train_vals = X[train_finite]
            q_lo = np.percentile(train_vals, 1)
            q_hi = np.percentile(train_vals, 99)

            signal = np.sign(np.clip(X, q_lo, q_hi))
            gross = signal * y

            test_gross = gross[test_mask]
            test_gross = test_gross[np.isfinite(test_gross)]

            if len(test_gross) > 0:
                mean_g, t_g, p_g, ci_g = block_bootstrap_ci(test_gross, block_size=100)
                window_results['features'][feat] = {
                    'gross_bps': float(mean_g),
                    'net_maker_bps': float(mean_g - MAKER_GATE_BPS),
                    'net_taker_bps': float(mean_g - TAKER_GATE_BPS),
                    'ci95_low': float(ci_g[0]),
                    'ci95_high': float(ci_g[1]),
                    'n_test': int(len(test_gross)),
                }

        # Best feature in this window
        if window_results['features']:
            best_feat = max(window_results['features'].items(),
                           key=lambda x: x[1]['gross_bps'])
            window_results['best_feature'] = best_feat[0]
            window_results['best_gross'] = best_feat[1]['gross_bps']
            window_results['best_net_maker'] = best_feat[1]['net_maker_bps']
            if verbose:
                print(f"  Window {w}: best={best_feat[0]}, "
                      f"gross={best_feat[1]['gross_bps']:.4f}, "
                      f"net_maker={best_feat[1]['net_maker_bps']:.4f}")

        results.append(window_results)

    return results


def determine_v8_verdict(feature_results: List[Dict], wf_results: List[Dict]) -> Dict:
    """Determine V8 final verdict based on all evaluation results."""
    if not feature_results:
        return {"verdict": "NOT_READY", "reason": "No valid feature results"}

    # Check if any feature passes the gate
    passing = []
    for r in feature_results:
        if r['gross_p_value'] < ALPHA and r['net_maker_bps'] > 0:
            passing.append(r)

    # Check walk-forward consistency
    wf_positive = 0
    wf_total = 0
    for wf in wf_results:
        if 'best_net_maker' in wf:
            wf_total += 1
            if wf['best_net_maker'] > 0:
                wf_positive += 1

    if passing:
        best = max(passing, key=lambda x: x['net_maker_bps'])
        return {
            "verdict": "PAPER_READY",
            "reason": f"Feature '{best['feature']}' passes: gross={best['gross_bps']:.4f} bps, "
                      f"net_maker={best['net_maker_bps']:.4f} bps, "
                      f"p={best['gross_p_value']:.6f}",
        }
    else:
        best_feature = max(feature_results, key=lambda x: x['gross_bps'])
        return {
            "verdict": "NOT_READY",
            "reason": f"No feature passes economic gate. Best: {best_feature['feature']} "
                      f"gross={best_feature['gross_bps']:.4f} bps, "
                      f"net_maker={best_feature['net_maker_bps']:.4f} bps, "
                      f"p={best_feature['gross_p_value']:.6f}. "
                      f"Walk-forward: {wf_positive}/{wf_total} windows positive.",
        }


def run_v8_validation(data_path: str | Path = None,
                       out_dir: str | Path = None,
                       horizon_ms: int = HORIZON_MS,
                       max_days: int = None,
                       verbose: bool = True) -> Dict:
    """Run full V8 validation pipeline.

    Steps:
    1. Compute V8 features from aggTrades (sampled)
    2. Add causal forward labels
    3. Chronological 70/15/15 split
    4. Compute size threshold from train only
    5. Evaluate each feature on ALL OOS events (not just size events)
    6. Apply economic gate (maker: 2.5 bps, taker: 4.5 bps)
    7. Walk-forward validation
    8. Permutation control
    9. Bonferroni-corrected significance
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Compute features
    if data_path and Path(data_path).exists():
        if verbose:
            print(f"Loading features from {data_path}")
        df = pd.read_parquet(data_path)
    else:
        # Compute from aggTrades
        aggtrades_dir = Path('data/hist/normalized/BTCUSDT/aggTrades')
        feature_path = out_dir / 'v8_features.parquet'

        if verbose:
            print("Step 1: Computing V8 features from aggTrades...")

        feature_path, size_threshold = compute_v8_features_aggtrades(
            aggtrades_dir, feature_path, max_days=max_days
        )
        df = pd.read_parquet(feature_path)

    # Step 2: Add causal forward labels
    if f'r_{horizon_ms}' not in df.columns:
        if verbose:
            print(f"Step 2: Adding forward labels at {horizon_ms}ms horizon...")
        df = add_causal_labels(df, horizon_ms)

    # Step 3: Chronological split
    ts_ms = df['ts_ms'].to_numpy(dtype=np.int64)
    train_mask, val_mask, oos_mask = chronological_split(ts_ms)

    if verbose:
        print(f"Step 3: Chronological split")
        print(f"  Train: {train_mask.sum():,} events")
        print(f"  Val:   {val_mask.sum():,} events")
        print(f"  OOS:   {oos_mask.sum():,} events")

    # Step 4: Compute size threshold from train only
    train_dv = df.loc[train_mask, 'dv_usd'].values
    size_threshold = np.percentile(train_dv, 99.9)
    if verbose:
        print(f"\nStep 4: Size threshold (train-only p99.9) = {size_threshold:.0f} USD")

    # Step 5: Evaluate each feature on ALL OOS events
    df_oos = df[oos_mask].copy()
    label_col = f'r_{horizon_ms}'

    if verbose:
        print(f"\nStep 5: Evaluating {len(V8_FEATURES)} features on {len(df_oos):,} OOS events")
        print(f"  Bonferroni α = {ALPHA:.5f}")

    results = []
    for feat in V8_FEATURES:
        if verbose:
            print(f"  Testing {feat}...")
        r = evaluate_v8_feature(df_oos, feat, horizon_ms)
        if r:
            results.append(r)
            passes = r['gross_p_value'] < ALPHA and r['net_maker_bps'] > 0
            if verbose:
                print(f"    Gross: {r['gross_bps']:.6f} bps (p={r['gross_p_value']:.6f})")
                print(f"    Net maker: {r['net_maker_bps']:.6f} bps")
                print(f"    Dates positive: {r['dates_positive']}/{r['total_dates']}")
                print(f"    Permutation mean: {r['perm_mean_bps']:.6f}")
                print(f"    Incremental vs perm: {r['incremental_vs_perm']:.6f}")
                print(f"    Passes gate: {passes}")

    # Step 6: Walk-forward validation
    if verbose:
        print(f"\nStep 6: Walk-forward validation (5 windows)...")

    wf_results = run_walk_forward_v8(df, V8_FEATURES, horizon_ms, verbose)

    # Step 7: Verdict
    verdict = determine_v8_verdict(results, wf_results)

    final = {
        'experiment_id': 'V8',
        'hypothesis': 'Trade-flow microstructure features from 730-day aggTrades provide incremental predictive edge',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'horizon_ms': horizon_ms,
        'n_total_events': int(len(df)),
        'n_train': int(train_mask.sum()),
        'n_val': int(val_mask.sum()),
        'n_oos': int(oos_mask.sum()),
        'size_threshold_usd': float(size_threshold),
        'split_fractions': list(SPLIT_FRACTIONS),
        'alpha_corrected': float(ALPHA),
        'features_tested': V8_FEATURES,
        'maker_gate_bps': MAKER_GATE_BPS,
        'taker_gate_bps': TAKER_GATE_BPS,
        'feature_results': results,
        'walk_forward': wf_results,
        'verdict': verdict['verdict'],
        'verdict_reason': verdict['reason'],
    }

    out_path = out_dir / 'v8_validation.json'
    out_path.write_text(json.dumps(final, indent=2, default=str))

    if verbose:
        print(f"\n=== V8 VERDICT: {verdict['verdict']} ===")
        print(f"Reason: {verdict['reason']}")
        print(f"\nResults saved to {out_path}")

    return final


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--features', type=str, default=None,
                    help='Path to pre-computed V8 features parquet')
    ap.add_argument('--out', type=Path,
                    default=Path('data/research/v8'))
    ap.add_argument('--horizon', type=int, default=HORIZON_MS)
    ap.add_argument('--max-days', type=int, default=None)
    a = ap.parse_args()

    run_v8_validation(
        data_path=a.features if a.features else None,
        out_dir=a.out,
        horizon_ms=a.horizon,
        max_days=a.max_days,
    )
