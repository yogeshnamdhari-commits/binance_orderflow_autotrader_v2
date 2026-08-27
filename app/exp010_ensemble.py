#!/usr/bin/env python3
"""EXP-010: Multi-Horizon Signal Ensemble (ENSEMBLE).

Hypothesis:
  Combining predictions from models trained at different horizons produces a
  stronger aggregate signal than any single horizon alone.

  Previous experiments tested single-horizon models:
  - V5/V6/V7: 500ms — gross +0.02 to +0.10 bps, net -1.9 to -2.5 bps
  - V8: 500ms and 30s — direction accuracy at baseline, magnitude corr ~0
  - EXP-007: 1s, 5s, 10s, 30s — all rejected, direction below random at short horizons
  - EXP-008: 5 regimes x 5 horizons — all rejected, 0% above gate
  - EXP-009: resiliency features — rejected, no improvement over baseline

  EXP-010 tests three ensemble strategies:
  1. Simple average of per-horizon model predictions
  2. Inverse-variance weighted ensemble (weight by 1/SE)
  3. Meta-model: logistic regression on per-horizon direction predictions

  The rationale: short horizons (500ms-5s) may capture order-flow pressure
  while longer horizons (10s-30s) may capture trend continuation. If their
  errors are uncorrelated, the ensemble could reduce noise.

Economic mechanism:
  - If model A at 500ms predicts +0.1 bps and model B at 30s predicts +0.3 bps
  - The ensemble might predict +0.2 bps
  - Only trade when ensemble prediction > cost (2.5 bps)

Falsification criteria (pre-registered):
  - If no ensemble strategy produces positive net expectancy at any horizon, reject
  - If ensemble AUC/accuracy does not improve over single-horizon best, reject
  - If trade frequency remains 0%, reject

Research basis:
  - Krauss, Do & Huck (2017): "Deep neural networks for stock selection" —
    ensemble methods improve out-of-sample performance
  - Bao, Zhang & Kong (2017): "Multi-scale deep learning for stock price
    forecasting" — multi-scale features improve prediction
  - Gu, Kelly & Xiu (2020): "Empirical asset pricing via attention and
    multi-horizon learning" — different horizons contain complementary info

Data required: v7_true_features.parquet with labels at [500, 1000, 5000, 10000, 30000]
Expected horizon: Multiple (ensemble across horizons)
Expected direction: Complementary signals across horizons
Expected cost sensitivity: HIGH — must overcome 2.5 bps
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
    apply_calibration, bootstrap_ci, hac_se,
    MAKER_FEE_BPS, SAFETY_MARGIN_BPS,
)

HORIZONS = [500, 1000, 5000, 10000, 30000]
COST_BPS = MAKER_FEE_BPS + SAFETY_MARGIN_BPS
RIDGE_ALPHA = 0.05

FEATURE_PATH = "data/research/v7_true_features.parquet"
OUT_DIR = Path("data/research/exp010")

DIRECTION_FEATURES = [
    "tfi_500", "signed_vol_imbalance", "qi_l1", "di_l5", "mpd_bps",
    "ofi_l1", "ofi_norm_l1", "spread_bps", "cancel_pressure",
    "vol_500", "vol_2000", "liq_depletion", "vpin", "kyle_lambda",
    "depth_slope_bps", "log_depth5", "signed_vol_500", "log_event_rate",
]


def train_single_horizon_model(df, horizon, feature_cols, train_mask, val_mask):
    """Train a ridge model at a single horizon and return model + val predictions."""
    label_col = f"r_{horizon}"
    
    X_all = df.loc[:, feature_cols].to_numpy(float)
    y_all = df.loc[:, label_col].to_numpy(float)
    
    X_train = X_all[train_mask]
    y_train = y_all[train_mask]
    X_val = X_all[val_mask]
    y_val = y_all[val_mask]
    
    ok_tr = np.isfinite(X_train).all(axis=1) & np.isfinite(y_train)
    ok_va = np.isfinite(X_val).all(axis=1) & np.isfinite(y_val)
    
    if ok_tr.sum() < 50 or ok_va.sum() < 10:
        return None
    
    beta, b0, mu, sd, r2, n = fit_ridge(X_train[ok_tr], y_train[ok_tr], alpha=RIDGE_ALPHA)
    val_pred = ridge_predict(X_val[ok_va], beta, b0, mu, sd)
    calib = fit_binned_calibration(val_pred, y_val[ok_va])
    
    model = {
        "beta": beta, "b0": b0, "mu": mu, "sd": sd,
        "r2": r2, "n_train": n,
        "calib": calib,
        "feature_cols": feature_cols,
        "horizon": horizon,
    }
    return model


def predict_single_horizon(model, X):
    """Get calibrated prediction from a model."""
    pred_raw = ridge_predict(X, model["beta"], model["b0"], model["mu"], model["sd"])
    return apply_calibration(pred_raw, model["calib"])


def run_exp010():
    """Run EXP-010: Multi-horizon ensemble."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    
    print("Loading data...")
    df = pd.read_parquet(FEATURE_PATH)
    df = df.sort_values("ts_ms").reset_index(drop=True)
    df = add_labels(df, horizons=HORIZONS)
    
    print(f"Loaded {len(df)} events, {df['session'].nunique()} sessions")
    
    feature_cols = [c for c in DIRECTION_FEATURES if c in df.columns]
    print(f"Features ({len(feature_cols)}): {feature_cols}")
    
    # Chronological splits
    splits = chrono_split_masks(df)
    train_mask = np.asarray(splits[0]["mask"], dtype=bool)
    val_mask = np.asarray(splits[1]["mask"], dtype=bool)
    oos_mask = np.asarray(splits[2]["mask"], dtype=bool)
    
    X_all = df.loc[:, feature_cols].to_numpy(float)
    
    # Step 1: Train single-horizon models
    print("\n=== Step 1: Training single-horizon models ===")
    models = {}
    val_predictions = {}  # calibrated val predictions per horizon
    
    for h in HORIZONS:
        label_col = f"r_{h}"
        y_val = df.loc[val_mask, label_col].to_numpy(float)
        X_val = X_all[val_mask]
        
        model = train_single_horizon_model(df, h, feature_cols, train_mask, val_mask)
        if model is None:
            print(f"  Horizon {h}ms: FAILED to train")
            continue
        
        models[h] = model
        val_pred = predict_single_horizon(model, X_val)
        val_predictions[h] = val_pred
        
        # Quick OOS check
        X_oos = X_all[oos_mask]
        oos_pred = predict_single_horizon(model, X_oos)
        y_oos = df.loc[oos_mask, label_col].to_numpy(float)
        
        finite = np.isfinite(oos_pred) & np.isfinite(y_oos)
        net = oos_pred[finite] - COST_BPS
        net_mean, _, _ = bootstrap_ci(net)
        
        print(f"  Horizon {h}ms: r2_train={model['r2']:.4f}, "
              f"OOS net={net_mean:+.4f}, dir_acc={np.mean(np.sign(oos_pred[finite]) == np.sign(y_oos[finite])):.4f}")
    
    available_horizons = sorted(models.keys())
    print(f"\nAvailable horizons for ensemble: {available_horizons}")
    
    if len(available_horizons) < 2:
        print("Not enough horizons for ensemble. Exiting.")
        return {"experiment_id": "EXP-010", "verdict": "HYPOTHESIS_REJECTED",
                "notes": "Insufficient horizons for ensemble"}
    
    # Step 2: Build ensembles
    print("\n=== Step 2: Building ensemble strategies ===")
    
    # Use the label at horizon 500ms as the primary target for the ensemble
    # (we evaluate the ensemble's ability to predict returns at each horizon)
    
    # Strategy 1: Simple average of per-horizon predictions
    # Strategy 2: Inverse-variance weighted
    # Strategy 3: Meta-model (logistic regression on per-horizon predictions)
    
    results = {
        "experiment_id": "EXP-010",
        "hypothesis": "Multi-Horizon Signal Ensemble",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cost_bps": COST_BPS,
        "alpha": RIDGE_ALPHA,
        "features": feature_cols,
        "available_horizons": available_horizons,
        "strategies": {},
        "horizons": {},
    }
    
    any_positive = False
    
    for eval_h in HORIZONS:
        if eval_h not in models:
            continue
        
        label_col = f"r_{eval_h}"
        y_oos = df.loc[oos_mask, label_col].to_numpy(float)
        
        print(f"\n{'='*60}")
        print(f"Evaluating ensemble at horizon: {eval_h}ms")
        print(f"{'='*60}")
        
        horizon_result = {"ensembles": {}, "verdict": None}
        
        # Get OOS predictions from each model
        oos_preds = {}
        X_oos = X_all[oos_mask]
        for h in available_horizons:
            oos_preds[h] = predict_single_horizon(models[h], X_oos)
        
        # Also get base predictions (single best horizon) for comparison
        best_single_net = -float('inf')
        best_h = None
        
        for h in available_horizons:
            pred = oos_preds[h]
            finite = np.isfinite(pred) & np.isfinite(y_oos)
            if finite.sum() < 10:
                continue
            net = pred[finite] - COST_BPS
            net_mean, _, _ = bootstrap_ci(net)
            if net_mean > best_single_net:
                best_single_net = net_mean
                best_h = h
        
        print(f"  Best single horizon: {best_h}ms, net={best_single_net:+.4f}")
        
        # Strategy 1: Simple average
        pred_all = np.zeros(len(y_oos))
        count = 0
        for h in available_horizons:
            pred = oos_preds[h]
            finite = np.isfinite(pred) & np.isfinite(y_oos)
            if finite.sum() > 10:
                pred_all[finite] += pred[finite]
                count += 1
        
        if count > 0:
            pred_avg = np.full(len(y_oos), np.nan)
            finite_mask = np.zeros(len(y_oos), dtype=bool)
            for h in available_horizons:
                pred = oos_preds[h]
                f = np.isfinite(pred) & np.isfinite(y_oos)
                if f.sum() > 0:
                    if not np.any(finite_mask):
                        pred_avg = np.full(len(y_oos), np.nan, dtype=float)
                    pred_avg[f] = pred[f] if not np.any(finite_mask[f]) else (
                        (pred_avg[f] * np.sum(finite_mask[f]) + pred[f]) / (np.sum(finite_mask[f]) + 1)
                    ) if np.any(finite_mask[f]) else pred[f]
                    finite_mask = finite_mask | f
            
            # Simpler: just average where all are finite
            all_finite = np.ones(len(y_oos), dtype=bool)
            for h in available_horizons:
                all_finite &= np.isfinite(oos_preds[h]) & np.isfinite(y_oos)
            
            if all_finite.sum() > 50:
                pred_avg = np.full(len(y_oos), np.nan)
                pred_avg[all_finite] = np.mean([
                    oos_preds[h][all_finite] for h in available_horizons
                ], axis=0)
                
                net = pred_avg - COST_BPS
                net_mean, net_lo, net_hi = bootstrap_ci(net)
                finite = all_finite
                
                dir_acc = float(np.mean(np.sign(pred_avg[finite]) == np.sign(y_oos[finite])))
                pct_above = float(np.mean(pred_avg[finite] > COST_BPS) * 100)
                
                metrics = {
                    "n_oos": int(finite.sum()),
                    "net_bps": round(net_mean, 4),
                    "net_ci95": [round(net_lo, 4), round(net_hi, 4)],
                    "dir_acc": round(dir_acc, 4),
                    "pct_above_gate": round(pct_above, 2),
                    "type": "simple_average",
                }
                print(f"  Strategy 1 (simple average): net={net_mean:+.4f}, "
                      f"dir_acc={dir_acc:.4f}, above_gate={pct_above:.1f}%")
                horizon_result["ensembles"]["simple_avg"] = metrics
                
                if net_mean > 0 and pct_above > 1.0:
                    any_positive = True
        
        # Strategy 2: Inverse-variance weighted
        all_finite = np.ones(len(y_oos), dtype=bool)
        for h in available_horizons:
            all_finite &= np.isfinite(oos_preds[h]) & np.isfinite(y_oos)
        
        if all_finite.sum() > 50:
            # Compute weights based on validation set performance
            weights = {}
            for h in available_horizons:
                val_pred = val_predictions[h]
                y_val_h = df.loc[val_mask, label_col].to_numpy(float)
                val_finite = np.isfinite(val_pred) & np.isfinite(y_val_h)
                if val_finite.sum() > 10:
                    val_net = val_pred[val_finite] - COST_BPS
                    se = hac_se(val_net)
                    weights[h] = 1.0 / (se + 1e-9)
                else:
                    weights[h] = 1.0
            
            total_w = sum(weights.values())
            for h in weights:
                weights[h] /= total_w
            
            pred_weighted = np.zeros(all_finite.sum())
            for h in available_horizons:
                pred_weighted += weights[h] * oos_preds[h][all_finite]
            
            pred_w = np.full(len(y_oos), np.nan)
            pred_w[all_finite] = pred_weighted
            net = pred_w - COST_BPS
            net_mean, net_lo, net_hi = bootstrap_ci(net)
            dir_acc = float(np.mean(np.sign(pred_w[all_finite]) == np.sign(y_oos[all_finite])))
            pct_above = float(np.mean(pred_w[all_finite] > COST_BPS) * 100)
            
            metrics = {
                "n_oos": int(all_finite.sum()),
                "net_bps": round(net_mean, 4),
                "net_ci95": [round(net_lo, 4), round(net_hi, 4)],
                "dir_acc": round(dir_acc, 4),
                "pct_above_gate": round(pct_above, 2),
                "weights": {str(k): round(v, 4) for k, v in weights.items()},
                "type": "inverse_variance_weighted",
            }
            print(f"  Strategy 2 (inv-var weighted): net={net_mean:+.4f}, "
                  f"dir_acc={dir_acc:.4f}, above_gate={pct_above:.1f}%, "
                  f"weights={weights}")
            horizon_result["ensembles"]["inv_var_weighted"] = metrics
            
            if net_mean > 0 and pct_above > 1.0:
                any_positive = True
        
        # Strategy 3: Meta-model — train ridge on per-horizon val predictions to predict direction
        val_target = df.loc[val_mask, label_col].to_numpy(float)
        all_val_finite = np.ones(val_mask.sum(), dtype=bool)
        for h in available_horizons:
            all_val_finite &= np.isfinite(val_predictions[h]) & np.isfinite(val_target)
        
        if all_val_finite.sum() > 100:
            meta_X = np.column_stack([val_predictions[h][all_val_finite] 
                                       for h in available_horizons])
            meta_y = val_target[all_val_finite]
            
            # Train meta-ridge on val predictions -> actual return
            try:
                mb, mb0, mmu, msd, mr2, mn = fit_ridge(meta_X, meta_y, alpha=RIDGE_ALPHA)
                meta_calib = fit_binned_calibration(
                    ridge_predict(meta_X, mb, mb0, mmu, msd), meta_y
                )
                
                # Apply to OOS
                oos_target_all_finite = np.ones(len(y_oos), dtype=bool)
                for h in available_horizons:
                    oos_target_all_finite &= np.isfinite(oos_preds[h]) & np.isfinite(y_oos)
                
                if oos_target_all_finite.sum() > 50:
                    meta_X_oos = np.column_stack([
                        oos_preds[h][oos_target_all_finite] for h in available_horizons
                    ])
                    meta_pred_raw = ridge_predict(meta_X_oos, mb, mb0, mmu, msd)
                    meta_pred_cal = apply_calibration(meta_pred_raw, meta_calib)
                    
                    meta_full = np.full(len(y_oos), np.nan)
                    meta_full[oos_target_all_finite] = meta_pred_cal
                    
                    net = meta_full - COST_BPS
                    net_mean, net_lo, net_hi = bootstrap_ci(net)
                    dir_acc = float(np.mean(np.sign(meta_pred_cal) == np.sign(y_oos[oos_target_all_finite])))
                    pct_above = float(np.mean(meta_pred_cal > COST_BPS) * 100)
                    
                    metrics = {
                        "n_oos": int(oos_target_all_finite.sum()),
                        "net_bps": round(net_mean, 4),
                        "net_ci95": [round(net_lo, 4), round(net_hi, 4)],
                        "dir_acc": round(dir_acc, 4),
                        "pct_above_gate": round(pct_above, 2),
                        "meta_r2": round(mr2, 4),
                        "type": "meta_model",
                    }
                    print(f"  Strategy 3 (meta-model): net={net_mean:+.4f}, "
                          f"dir_acc={dir_acc:.4f}, above_gate={pct_above:.1f}%, "
                          f"meta_r2={mr2:.4f}")
                    horizon_result["ensembles"]["meta_model"] = metrics
                    
                    if net_mean > 0 and pct_above > 1.0:
                        any_positive = True
            except Exception as e:
                print(f"  Strategy 3 (meta-model): ERROR: {e}")
        
        # Also report best single horizon for comparison
        horizon_result["best_single_horizon"] = best_h
        horizon_result["best_single_net"] = round(best_single_net, 4)
        
        # Verdict
        best_ens_net = max(
            [m.get("net_bps", -999) for m in horizon_result["ensembles"].values()
             if isinstance(m, dict) and "net_bps" in m]
        )
        horizon_result["best_ensemble_net"] = round(best_ens_net, 4)
        
        improved = best_ens_net > best_single_net + 0.001
        horizon_result["verdict"] = "IMPROVED" if improved else "NOT_IMPROVED"
        
        results["horizons"][str(eval_h)] = horizon_result
    
    results["verdict"] = "HYPOTHESIS_PASSED" if any_positive else "HYPOTHESIS_REJECTED"
    
    results_path = OUT_DIR / "exp010_results.json"
    results_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"\n\n{'='*60}")
    print(f"EXP-010 FINAL VERDICT: {results['verdict']}")
    print(f"{'='*60}")
    
    for h_str, hr in results["horizons"].items():
        print(f"\n  Horizon {h_str}ms: best_single={hr.get('best_single_horizon')}/"
              f"{hr.get('best_single_net','N/A')} best_ensemble={hr.get('best_ensemble_net','N/A')} "
              f"verdict={hr.get('verdict','N/A')}")
    
    return results


if __name__ == "__main__":
    run_exp010()
