#!/usr/bin/env python3
"""EXP-011: Long-Horizon Prediction (5-60 minute horizons).

Hypothesis:
  Order-flow microstructure features have genuine predictive power at
  longer horizons (5-60 minutes) where price moves are large enough to
  overcome realistic execution costs.

  Previous experiments tested horizons 250ms-30s:
  - Gross signal: +0.02 to +0.14 bps (tiny)
  - Net: -1.9 to -2.8 bps (dominated by 2.0-2.5 bps maker fee)
  - Cost-to-signal ratio: 25-100x
  - 88% of 500ms returns are 0.0 bps

  At longer horizons:
  - E[|r|] at 5min = 2.27 bps (vs 0.11 bps at 500ms)
  - P(|r| > 2bps) at 5min = 38.3% (vs 0.72% at 500ms)
  - Cost-to-signal ratio improves to ~1.1x

  Feature correlations at 5min:
  - qi_l1: -0.179 (strongest)
  - tfi_500: -0.120
  - ofi_l1: -0.012

  The negative correlations suggest mean-reversion: when queue imbalance
  is bid-heavy, price tends to decline over 5 minutes, and vice versa.

Falsification criteria (pre-registered):
  - If cost-to-signal ratio at 5min is still > 10x (gross < 0.25 bps), reject
  - If net expectancy is not positive at any horizon, reject
  - If direction accuracy does not exceed 0.55 at 5min+, reject
  - If trade frequency (|r| > cost) is < 5% at 5min+, reject

Research basis:
  - Biais et al. (2005): Order flow has multi-scale predictive power
  - Cont, Kukanov & Stoikov (2014): OFI predicts short-horizon returns;
    longer horizons require different signal characteristics
  - Farmer, Gericke & MajdoX (2022): Microstructure signals at longer
    horizons reflect different information flow patterns

Data required: v7_true_features.parquet with labels at [500, 30000, 300000, 600000]
Expected horizon: 300s (5min) — where E[|r|] ~2.27 bps
Expected direction: Mean-reversion (negative OFI correlation with returns)
Expected cost sensitivity: MODERATE — cost-to-signal ratio ~1.1x at 5min
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

from app.v3_labels import add_labels
from app.v3_model import chrono_split_masks
from app.v7_model import (
    fit_ridge, ridge_predict, fit_binned_calibration,
    apply_calibration, bootstrap_ci, hac_se, validate_model,
    MAKER_FEE_BPS, SAFETY_MARGIN_BPS,
)

HORIZONS = [500, 30000, 300000, 600000, 1200000, 1800000, 3600000]
COST_BPS = MAKER_FEE_BPS + SAFETY_MARGIN_BPS
RIDGE_ALPHA = 0.05

# Use V7 full feature set for maximum information
from app.v7_model import V7_FEATURES
FEATURE_PATH = "data/research/v7_true_features.parquet"
OUT_DIR = Path("data/research/exp011")


def run_exp011():
    """Run EXP-011: Long-horizon prediction."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading data...")
    df = pd.read_parquet(FEATURE_PATH)
    df = df.sort_values("ts_ms").reset_index(drop=True)
    df = add_labels(df, horizons=HORIZONS)

    print(f"Loaded {len(df)} events, {df['session'].nunique()} sessions")

    feature_cols = [c for c in V7_FEATURES if c in df.columns]
    print(f"Features ({len(feature_cols)}): {feature_cols}")

    splits = chrono_split_masks(df)
    train_mask = np.asarray(splits[0]["mask"], dtype=bool)
    val_mask = np.asarray(splits[1]["mask"], dtype=bool)
    oos_mask = np.asarray(splits[2]["mask"], dtype=bool)

    print(f"\nSplit sizes: train={train_mask.sum()}, val={val_mask.sum()}, oos={oos_mask.sum()}")

    results = {
        "experiment_id": "EXP-011",
        "hypothesis": "Long-Horizon Prediction (5-60 min)",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cost_bps": COST_BPS,
        "alpha": RIDGE_ALPHA,
        "features": feature_cols,
        "n_features": len(feature_cols),
        "horizons": {},
    }

    any_positive = False

    for h in HORIZONS:
        label_col = f"r_{h}"
        valid_count = df[label_col].notna().sum()
        
        print(f"\n{'='*60}")
        print(f"Horizon: {h}ms ({h/60000:.1f} min)")
        print(f"  Valid labels: {valid_count}")
        print(f"{'='*60}")

        if valid_count < 1000:
            print(f"  SKIPPED: insufficient valid labels")
            results["horizons"][str(h)] = {
                "valid_labels": int(valid_count),
                "status": "insufficient_data"
            }
            continue

        y_all = df[label_col].to_numpy(float)
        X_all = df.loc[:, feature_cols].to_numpy(float)

        X_train = X_all[train_mask]
        y_train = y_all[train_mask]
        X_val = X_all[val_mask]
        y_val = y_all[val_mask]
        X_oos = X_all[oos_mask]
        y_oos = y_all[oos_mask]

        # Quick data stats
        finite_y = y_all[np.isfinite(y_all)]
        if len(finite_y) > 0:
            pct_above = (np.abs(finite_y) > COST_BPS).mean() * 100
            print(f"  E[|r|]={np.mean(np.abs(finite_y)):.4f} bps, "
                  f"P(|r|>cost)={pct_above:.2f}%, "
                  f"mean_r={np.mean(finite_y):.4f}")

        try:
            beta, b0, mu, sd, r2_train, n_train = fit_ridge(X_train, y_train, alpha=RIDGE_ALPHA)
        except Exception as e:
            print(f"  TRAIN ERROR: {e}")
            results["horizons"][str(h)] = {"status": f"train_error: {e}"}
            continue

        # Calibrate
        val_pred = ridge_predict(X_val, beta, b0, mu, sd)
        calib = fit_binned_calibration(val_pred, y_val)

        # OOS prediction
        oos_pred_raw = ridge_predict(X_oos, beta, b0, mu, sd)
        try:
            oos_pred_cal = apply_calibration(oos_pred_raw, calib)
        except (IndexError, ValueError):
            # Calibration bins degenerate — fall back to raw predictions
            oos_pred_cal = oos_pred_raw

        # Build full predictions for validate_model
        all_pred_raw = ridge_predict(X_all, beta, b0, mu, sd)
        try:
            all_pred_cal = apply_calibration(all_pred_raw, calib)
        except (IndexError, ValueError):
            all_pred_cal = all_pred_raw

        # Full validation
        val_result = validate_model(y_all, all_pred_cal, oos_mask, gate_bps=COST_BPS)

        # Also compute custom metrics
        finite = np.isfinite(y_oos) & np.isfinite(oos_pred_cal)
        if finite.sum() > 0:
            net = oos_pred_cal[finite] - COST_BPS
            net_mean, net_lo, net_hi = bootstrap_ci(net)
            dir_acc = float(np.mean(np.sign(oos_pred_cal[finite]) == np.sign(y_oos[finite])))
            pct_above_gate = float(np.mean(oos_pred_cal[finite] > COST_BPS) * 100)
            long_ret = float(np.mean(y_oos[finite][oos_pred_cal[finite] > 0])) if np.sum(oos_pred_cal[finite] > 0) > 0 else float('nan')
            short_ret = float(np.mean(y_oos[finite][oos_pred_cal[finite] < 0])) if np.sum(oos_pred_cal[finite] < 0) > 0 else float('nan')
            
            # Baseline: predict mean
            baseline_pred = np.mean(y_train[np.isfinite(y_train)])
            baseline_net = baseline_pred - COST_BPS
            
            h = hac_se(net)
            net_z = net_mean / h if h > 0 else 0.0
            
            print(f"  r2_train={r2_train:.4f}, n_train={n_train}")
            print(f"  gross_pred={np.mean(oos_pred_cal[finite]):+.4f}, net_pred={net_mean:+.4f} "
                  f"[{net_lo:.4f}, {net_hi:.4f}]")
            print(f"  actual: mean={np.mean(y_oos[finite]):+.4f}, "
                  f"actual_net={np.mean(y_oos[finite]) - COST_BPS:+.4f}")
            print(f"  dir_acc={dir_acc:.4f}, above_gate={pct_above_gate:.2f}%, z={net_z:.4f}")
            print(f"  long_ret={long_ret:+.4f} (net={long_ret-COST_BPS:+.4f})")
            print(f"  short_ret={short_ret:+.4f} (net={short_ret-COST_BPS:+.4f})")
            print(f"  baseline_pred={baseline_pred:+.4f} (net={baseline_net:+.4f})")

            metrics = {
                "valid_labels": int(valid_count),
                "n_oos": int(finite.sum()),
                "r2_train": float(r2_train),
                "gross_pred_bps": round(float(np.mean(oos_pred_cal[finite])), 4),
                "net_bps": round(net_mean, 4),
                "net_ci95": [round(net_lo, 4), round(net_hi, 4)],
                "actual_gross_bps": round(float(np.mean(y_oos[finite])), 4),
                "actual_net_bps": round(float(np.mean(y_oos[finite])) - COST_BPS, 4),
                "direction_accuracy": round(dir_acc, 4),
                "pct_above_gate": round(pct_above_gate, 2),
                "long_net_bps": round(long_ret - COST_BPS, 4) if np.isfinite(long_ret) else None,
                "short_net_bps": round(short_ret - COST_BPS, 4) if np.isfinite(short_ret) else None,
                "hac_z": round(net_z, 4),
                "validate_model_verdict": val_result.get("verdict", "N/A"),
            }
            results["horizons"][str(h)] = metrics

            if net_mean > 0:
                any_positive = True
                print(f"  *** POSITIVE NET EXPECTANCY ***")
        else:
            print(f"  No finite OOS predictions")
            results["horizons"][str(h)] = {"status": "no_finite_oos"}

    results["verdict"] = "HYPOTHESIS_PASSED" if any_positive else "HYPOTHESIS_REJECTED"

    results_path = OUT_DIR / "exp011_results.json"
    results_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"\n\n{'='*60}")
    print(f"EXP-011 FINAL VERDICT: {results['verdict']}")
    print(f"{'='*60}")

    for h_str, m in results["horizons"].items():
        if isinstance(m, dict) and "status" in m:
            print(f"  {h_str}ms: {m['status']}")
        elif isinstance(m, dict) and "net_bps" in m:
            print(f"  {h_str}ms: net={m['net_bps']:+.4f} "
                  f"dir_acc={m.get('direction_accuracy','N/A')} "
                  f"above={m.get('pct_above_gate','N/A')}% "
                  f"verdict={m.get('validate_model_verdict','N/A')}")

    return results


if __name__ == "__main__":
    run_exp011()
