#!/usr/bin/env python3
"""EXP-007: Horizon-Matched Feature Aggregation (HORIZON-OFI).

Key insight from V5-V8 failures:
  V8 at 30s used 500ms-scale features (tfi_500, vpin from 500ms) to predict 30s returns.
  This is a feature-horizon mismatch.

Hypothesis:
  Features computed at the SAME scale as the prediction horizon contain
  more predictive information than fixed-scale features.

  At 30s, P(|r| > 2 bps) = 9.5% vs 0.7% at 500ms.
  If we compute OFI, trade flow, depth features at 30s scale,
  we can predict 30s returns better than 500ms features.

Method:
  For each horizon h in {1s, 5s, 10s, 30s}:
    1. Compute features aggregated over trailing window h
    2. Train ridge model to predict r_h
    3. Evaluate OOS net expectancy

Research basis:
  - Cont, Kukanov & Stoikov (2014): OFI-price impact is horizon-dependent
  - Features must match the prediction scale
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

from app.v3_labels import add_labels
from app.v3_model import chrono_split_masks, fit_horizon, SPLIT_FRACTIONS
from app.v7_model import fit_binned_calibration, apply_calibration, bootstrap_ci, validate_model

HORIZONS = [1000, 5000, 10000, 30000]
COST_BPS = 2.5


def compute_horizon_features(df, horizon_ms):
    """Compute features aggregated over the trailing window matching the horizon."""
    rows = []
    ts = df['ts_ms'].to_numpy(dtype=np.int64)
    
    for i in range(len(df)):
        # Find events in trailing window
        t = ts[i]
        mask = (ts >= t - horizon_ms) & (ts < t)
        j = np.where(mask)[0]
        
        if len(j) < 2:
            rows.append(None)
            continue
        
        # Price changes in window
        mid = df['mid'].to_numpy(float)
        price_changes = np.diff(mid[j])
        
        # OFI at horizon scale: net order flow
        if 'ofi_l1' in df.columns:
            ofi_window = df['ofi_l1'].to_numpy(float)[j]
            ofi_sum = np.sum(ofi_window)
        else:
            ofi_sum = 0.0
        
        # Trade flow at horizon scale
        if 'tfi_500' in df.columns:
            # Sum of signed trade imbalances
            tfi_window = df['tfi_500'].to_numpy(float)[j[1:]]  # align with diffs
            if len(tfi_window) > 0:
                tfi_sum = np.sum(tfi_window)
                tfi_mean = np.mean(tfi_window)
            else:
                tfi_sum = 0.0
                tfi_mean = 0.0
        else:
            tfi_sum = 0.0
            tfi_mean = 0.0
        
        # Volatility at horizon scale
        if len(price_changes) >= 2:
            vol = np.std(price_changes) * 1e4  # in bps
        else:
            vol = 0.0
        
        # Depth changes
        if 'log_depth5' in df.columns:
            depth = df['log_depth5'].to_numpy(float)
            depth_change = depth[i] - depth[j[0]] if len(j) > 0 else 0.0
        else:
            depth_change = 0.0
        
        # VPIN at horizon scale (mean |tfi|)
        vpin_h = np.mean(np.abs(df['tfi_500'].to_numpy(float)[j[1:]])) if len(j) > 1 else 0.0
        
        # Return autocorrelation
        if len(price_changes) >= 3:
            autocorr = np.corrcoef(price_changes[:-1], price_changes[1:])[0, 1] if np.std(price_changes) > 0 else 0.0
            if not np.isfinite(autocorr):
                autocorr = 0.0
        else:
            autocorr = 0.0
        
        # Current state (snapshot)
        qi = df['qi_l1'].to_numpy(float)[i] if 'qi_l1' in df.columns else 0.0
        spread = df['spread_bps'].to_numpy(float)[i] if 'spread_bps' in df.columns else 0.0
        mpd = df['mpd_bps'].to_numpy(float)[i] if 'mpd_bps' in df.columns else 0.0
        
        rows.append({
            'ofi_h': ofi_sum,
            'tfi_sum_h': tfi_sum,
            'tfi_mean_h': tfi_mean,
            'vol_h': vol,
            'depth_change_h': depth_change,
            'vpin_h': vpin_h,
            'autocorr_h': autocorr,
            'qi_cur': qi,
            'spread_cur': spread,
            'mpd_cur': mpd,
        })
    
    # Filter out None rows
    valid_indices = [i for i, r in enumerate(rows) if r is not None]
    features = pd.DataFrame([rows[i] for i in valid_indices])
    
    return features, valid_indices


def run_exp007(feature_path, out_dir):
    """Run EXP-007 for all horizons."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    df = pd.read_parquet(feature_path)
    df = add_labels(df, horizons=HORIZONS)
    
    results = {
        "experiment_id": "EXP-007",
        "hypothesis": "Horizon-Matched Feature Aggregation",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cost_bps": COST_BPS,
        "horizons": {},
    }
    
    for h in HORIZONS:
        label_col = f'r_{h}'
        
        # Compute horizon-matched features
        features, valid_idx = compute_horizon_features(df, h)
        
        # Align labels with valid indices
        y_all = df[label_col].to_numpy(float)
        y_valid = y_all[valid_idx]
        
        # Filter finite
        finite = np.isfinite(y_valid) & np.isfinite(features).all(axis=1).to_numpy()
        features_f = features.loc[finite].reset_index(drop=True)
        y_f = y_valid[finite]
        
        if len(y_f) < 200:
            results["horizons"][str(h)] = {"error": "Insufficient data"}
            continue
        
        # Chronological split
        n = len(y_f)
        train_end = int(n * 0.7)
        val_end = int(n * 0.85)
        
        X_train = features_f.iloc[:train_end].to_numpy(float)
        y_train = y_f[:train_end]
        X_val = features_f.iloc[train_end:val_end].to_numpy(float)
        y_val = y_f[train_end:val_end]
        X_oos = features_f.iloc[val_end:].to_numpy(float)
        y_oos = y_f[val_end:]
        
        # Fit ridge
        try:
            from app.v7_model import fit_ridge, ridge_predict
            beta, b0, mu, sd, r2, n_train = fit_ridge(X_train, y_train)
            
            # Calibrate on validation
            val_pred = ridge_predict(X_val, beta, b0, mu, sd)
            calib = fit_binned_calibration(val_pred, y_val)
            
            # OOS prediction
            oos_pred = ridge_predict(X_oos, beta, b0, mu, sd)
            oos_pred_cal = apply_calibration(oos_pred, calib)
            
            # Metrics
            n_oos = len(y_oos)
            gross = float(np.mean(oos_pred_cal))
            net = gross - COST_BPS
            gross_actual = float(np.mean(y_oos))
            net_actual = gross_actual - COST_BPS
            
            # CI
            _, ci_low, ci_high = bootstrap_ci(oos_pred_cal - COST_BPS)
            
            # Direction accuracy
            dir_acc = float(np.mean(np.sign(oos_pred_cal) == np.sign(y_oos)))
            
            # % above gate
            pct_above = float(np.mean(oos_pred_cal > COST_BPS) * 100)
            
            results["horizons"][str(h)] = {
                "n_oos": n_oos,
                "gross_predicted_bps": round(gross, 4),
                "gross_actual_bps": round(gross_actual, 4),
                "net_bps": round(net_actual, 4),
                "net_ci95": [round(ci_low, 4), round(ci_high, 4)],
                "direction_accuracy": round(dir_acc, 4),
                "pct_above_gate": round(pct_above, 2),
                "n_features": features_f.shape[1],
                "feature_names": features_f.columns.tolist(),
            }
        except Exception as e:
            results["horizons"][str(h)] = {"error": str(e)}
    
    # Save
    (out_dir / "exp007_results.json").write_text(json.dumps(results, indent=2, default=str))
    
    return results


def print_results(results):
    """Compact output."""
    print("=" * 70)
    print(f"EXP-007: {results['hypothesis']}")
    print("=" * 70)
    print(f"{'Horizon':>8s} {'Gross':>8s} {'Net':>8s} {'CI_low':>8s} {'CI_high':>8s} {'DirAcc':>8s} {'%Gate':>8s} {'N_oos':>8s}")
    print("-" * 70)
    for h, r in results["horizons"].items():
        if "error" in r:
            print(f"{h:>8s} ERROR: {r['error']}")
        else:
            print(f"{h:>8s} {r['gross_actual_bps']:>+8.4f} {r['net_bps']:>+8.4f} "
                  f"{r['net_ci95'][0]:>+8.4f} {r['net_ci95'][1]:>+8.4f} "
                  f"{r['direction_accuracy']:>8.4f} {r['pct_above_gate']:>7.2f}% {r['n_oos']:>8d}")
    print("=" * 70)


if __name__ == "__main__":
    results = run_exp007("data/research/v7_true_features.parquet", "data/research/exp007")
    print_results(results)
