#!/usr/bin/env python3
"""V7 final validation — V5 baseline vs V7 on identical data.

Runs staged model comparison on the SAME dataset (v7_true_features.parquet)
for fair evaluation. V5 baseline uses 17 original features; V7 uses all 61.

Pre-registered analysis:
  1. V5 baseline (ridge, 17 features)
  2. V7 ridge (all features)
  3. V7 ridge (ablated feature subsets)
  4. Economic gate evaluation
  5. Statistical significance (bootstrap CI, HAC SE)
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict

from app.v3_labels import add_labels
from app.v3_model import chrono_split_masks, SPLIT_FRACTIONS
from app.v7_model import (
    fit_ridge, ridge_predict, fit_binned_calibration, apply_calibration,
    bootstrap_ci, hac_se, economic_gate, validate_model,
    V5_FEATURES, MAKER_FEE_BPS, SAFETY_MARGIN_BPS, PRIMARY_HORIZON
)

# V7 feature groups (from true multi-level computation)
V7_MULTI_LEVEL_OFI = ["ofi_l2", "ofi_l3", "ofi_l4", "ofi_l5", "ofi_l6",
                      "ofi_l7", "ofi_l8", "ofi_l9", "ofi_l10",
                      "mlofi_weighted", "ofi_decay", "ofi_net_levels"]
V7_QUEUE = ["qi_l2", "qi_l3", "qi_l5", "qi_l10", "qi_multi", "qi_slope", "qi_accel"]
V7_MICROPRICE = ["mp_vel", "mp_reversion"]
V7_TOXICITY = ["vpin", "kyle_lambda", "signed_vol_imbalance"]
V7_STRUCTURE = ["depth_slope_levels", "depth_asymmetry"]
V7_VOLATILITY = ["vol_ratio"]
V7_INTERACTIONS = ["ofi_x_qi", "mlofi_x_spread"]

V7_ALL_NEW = V7_MULTI_LEVEL_OFI + V7_QUEUE + V7_MICROPRICE + V7_TOXICITY + V7_STRUCTURE + V7_VOLATILITY + V7_INTERACTIONS
V7_ALL_FEATURES = V5_FEATURES + V7_ALL_NEW


def run_validation(feature_path: str | Path, out_dir: str | Path,
                   horizon_ms: int = PRIMARY_HORIZON):
    """Run full V7 validation pipeline."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Load data
    df = pd.read_parquet(feature_path)
    df = add_labels(df, horizons=(horizon_ms,))
    label_col = f"r_{horizon_ms}"
    
    # Filter valid rows
    all_features = list(set(V7_ALL_FEATURES + [label_col, "mid", "spread_bps", "regime", "session"]))
    existing_features = [f for f in all_features if f in df.columns]
    mask = (
        df["mid"].notna() & (df["mid"] > 0) &
        df["spread_bps"].notna() & (df["spread_bps"] > 0) &
        df[existing_features].notna().all(axis=1)
    )
    df = df.loc[mask].reset_index(drop=True)
    
    # Splits
    splits = chrono_split_masks(df)
    train_mask = splits[0]["mask"]
    val_mask = splits[1]["mask"]
    oos_mask = splits[2]["mask"]
    
    y_all = df[label_col].to_numpy(float)
    
    results = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "horizon_ms": horizon_ms,
        "dataset": str(feature_path),
        "n_total": len(df),
        "n_train": int(train_mask.sum()),
        "n_val": int(val_mask.sum()),
        "n_oos": int(oos_mask.sum()),
        "sessions": df["session"].unique().tolist(),
    }
    
    # Model 0: Naive baseline
    y_train = y_all[train_mask]
    naive_mean = np.mean(y_train[np.isfinite(y_train)])
    naive_pred = np.full(len(df), naive_mean)
    results["model_0_naive"] = validate_model(y_all, naive_pred, oos_mask)
    
    # Model 1: V5 baseline (17 features)
    v5_features = [f for f in V5_FEATURES if f in df.columns]
    X_all_v5 = df[v5_features].to_numpy(float)
    X_train = X_all_v5[train_mask]
    y_train = y_all[train_mask]
    X_val = X_all_v5[val_mask]
    y_val = y_all[val_mask]
    
    beta_v5, b0_v5, mu_v5, sd_v5, r2_v5, n_v5 = fit_ridge(X_train, y_train)
    val_pred_v5 = ridge_predict(X_val, beta_v5, b0_v5, mu_v5, sd_v5)
    calib_v5 = fit_binned_calibration(val_pred_v5, y_val)
    all_pred_v5 = ridge_predict(X_all_v5, beta_v5, b0_v5, mu_v5, sd_v5)
    all_pred_v5_cal = apply_calibration(all_pred_v5, calib_v5)
    
    results["model_1_v5_baseline"] = validate_model(y_all, all_pred_v5_cal, oos_mask)
    results["model_1_v5_baseline"]["r2_train"] = float(r2_v5)
    results["model_1_v5_baseline"]["n_features"] = len(v5_features)
    
    # Model 2: V7 full features
    v7_features = [f for f in V7_ALL_FEATURES if f in df.columns]
    X_all_v7 = df[v7_features].to_numpy(float)
    X_train_v7 = X_all_v7[train_mask]
    X_val_v7 = X_all_v7[val_mask]
    
    beta_v7, b0_v7, mu_v7, sd_v7, r2_v7, n_v7 = fit_ridge(X_train_v7, y_train)
    val_pred_v7 = ridge_predict(X_val_v7, beta_v7, b0_v7, mu_v7, sd_v7)
    calib_v7 = fit_binned_calibration(val_pred_v7, y_val)
    all_pred_v7 = ridge_predict(X_all_v7, beta_v7, b0_v7, mu_v7, sd_v7)
    all_pred_v7_cal = apply_calibration(all_pred_v7, calib_v7)
    
    results["model_2_v7_full"] = validate_model(y_all, all_pred_v7_cal, oos_mask)
    results["model_2_v7_full"]["r2_train"] = float(r2_v7)
    results["model_2_v7_full"]["n_features"] = len(v7_features)
    
    # Ablation study
    subsets = {
        "V5_baseline": v5_features,
        "V5_plus_multi_level_ofi": v5_features + [f for f in V7_MULTI_LEVEL_OFI if f in df.columns],
        "V5_plus_queue": v5_features + [f for f in V7_QUEUE if f in df.columns],
        "V5_plus_microprice": v5_features + [f for f in V7_MICROPRICE if f in df.columns],
        "V5_plus_toxicity": v5_features + [f for f in V7_TOXICITY if f in df.columns],
        "V5_plus_structure": v5_features + [f for f in V7_STRUCTURE if f in df.columns],
        "V5_plus_volatility": v5_features + [f for f in V7_VOLATILITY if f in df.columns],
        "V5_plus_interactions": v5_features + [f for f in V7_INTERACTIONS if f in df.columns],
        "V7_full": v7_features,
    }
    
    ablation = {}
    for name, features in subsets.items():
        X_sub = df[features].to_numpy(float)
        try:
            beta_s, b0_s, mu_s, sd_s, r2_s, n_s = fit_ridge(X_sub[train_mask], y_train)
            val_pred_s = ridge_predict(X_sub[val_mask], beta_s, b0_s, mu_s, sd_s)
            calib_s = fit_binned_calibration(val_pred_s, y_val)
            all_pred_s = ridge_predict(X_sub, beta_s, b0_s, mu_s, sd_s)
            all_pred_s_cal = apply_calibration(all_pred_s, calib_s)
            res = validate_model(y_all, all_pred_s_cal, oos_mask)
            res["r2_train"] = float(r2_s)
            res["n_features"] = len(features)
            ablation[name] = res
        except Exception as e:
            ablation[name] = {"error": str(e)}
    
    results["ablation"] = ablation
    
    # Save
    (out_dir / "v7_final_validation.json").write_text(
        json.dumps(results, indent=1, default=str))
    
    return results


def print_results(results: Dict):
    """Pretty-print validation results."""
    print("=" * 80)
    print("V7 FINAL VALIDATION REPORT")
    print("=" * 80)
    print(f"Generated: {results['generated_at']}")
    print(f"Horizon: {results['horizon_ms']} ms")
    print(f"Dataset: {results['dataset']}")
    print(f"Sessions: {len(results['sessions'])}")
    print(f"Total rows: {results['n_total']}, Train: {results['n_train']}, "
          f"Val: {results['n_val']}, OOS: {results['n_oos']}")
    
    print("\n" + "-" * 80)
    print("MODEL RESULTS")
    print("-" * 80)
    print(f"{'Model':30s} {'Gross bps':>12s} {'Net bps':>12s} {'CI_low':>10s} {'CI_high':>10s} {'%Gate':>8s} {'Verdict':>15s}")
    print("-" * 80)
    
    for name in ["model_0_naive", "model_1_v5_baseline", "model_2_v7_full"]:
        if name in results:
            r = results[name]
            print(f"{name:30s} {r['gross_mean_bps']:+12.4f} {r['net_mean_bps']:+12.4f} "
                  f"{r['net_ci95_low']:+10.4f} {r['net_ci95_high']:+10.4f} "
                  f"{r['pct_above_gate']:7.2f}% {r['verdict']:>15s}")
    
    if "ablation" in results:
        print("\n" + "-" * 80)
        print("ABLATION STUDY")
        print("-" * 80)
        print(f"{'Subset':35s} {'Gross bps':>12s} {'Net bps':>12s} {'%Gate':>8s} {'N_feat':>6s} {'Verdict':>15s}")
        print("-" * 80)
        
        for name, r in results["ablation"].items():
            if "error" not in r:
                print(f"{name:35s} {r['gross_mean_bps']:+12.4f} {r['net_mean_bps']:+12.4f} "
                      f"{r['pct_above_gate']:7.2f}% {r['n_features']:6d} {r['verdict']:>15s}")
            else:
                print(f"{name:35s} ERROR: {r['error']}")
    
    print("\n" + "=" * 80)
    
    # Final verdict
    v7 = results.get("model_2_v7_full", {})
    v5 = results.get("model_1_v5_baseline", {})
    
    if v7.get("verdict") == "POSITIVE_EDGE":
        print("V7 VERDICT: POSITIVE_EDGE — V7 features show executable edge")
    elif v7.get("net_mean_bps", -999) > v5.get("net_mean_bps", -999):
        print("V7 VERDICT: IMPROVED_BUT_NEGATIVE — V7 better than V5 but still negative net")
    else:
        print("V7 VERDICT: NO_EDGE — V7 features do not provide executable edge")
    
    print("=" * 80)


if __name__ == "__main__":
    results = run_validation(
        feature_path="data/research/v7_true_features.parquet",
        out_dir="data/research/v7"
    )
    print_results(results)
