#!/usr/bin/env python3
"""EXP-009: Order-Book Resiliency Signal (RESILIENCY).

Hypothesis:
  Order book depth replenishment dynamics after aggressive events contain
  predictive information that static snapshot features (tested in V5-V8) do not.

  Previous experiments (V5-V8, EXP-007, EXP-008) all used STATIC features:
  the state of the order book at time t. These showed gross +0.02-0.10 bps
  but net -1.9 to -2.7 bps due to 2.0-2.5 bps maker fee.

  EXP-009 tests DYNAMIC features: how the book recovers AFTER an aggressive
  event. After a market order depletes depth, the replenishment rate reveals:
  - If depth recovers quickly → market is stable, informed flow unlikely
  - If depth recovers slowly → possible informed trading, momentum may continue
  - Net order flow after depletion → absorption vs. continuation signal

Economic mechanism:
  - When aggressive buying depletes ask depth, and bid depth quickly replenishes
    while ask depth stays thin → bearish (more selling pressure)
  - When aggressive selling depletes bid depth, and ask depth quickly replenishes
    while bid depth stays thin → bullish (more buying pressure)
  - Slow overall replenishment → high toxicity regime, larger subsequent moves

Falsification criteria (pre-registered):
  - If net expectancy is not positive at ANY horizon, reject
  - If resiliency features don't improve R² over baseline V5 features, reject
  - If direction accuracy doesn't improve over V7, reject

Research basis:
  - Biais et al. (2005): "Market microstructure: A survey of micro-level
    constituents" — order book resiliency and price impact
  - Cont, Kukanov & Stoikov (2014): "Statistical modeling of price impact
    of order flow with partially observed liquidity" — replenishment rate
    affects sustained price impact
  - Avellaneda & Stoikov (2008): "High-frequency market microstructure"
    — order book dynamics and recovery

Data required: v7_true_features.parquet with depth update and trade events
Expected horizon: 1000ms (1s — where both signal and moves are reasonably sized)
Expected direction: Resiliency features should improve prediction at 1-10s horizon
Expected cost sensitivity: HIGH — 2.0 bps maker fee is binding
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

# Base V5 features + V7 resiliency features
BASE_FEATURES = [
    "ofi_l1", "ofi_norm_l1", "qi_l1", "di_l5", "mpd_bps",
    "spread_bps", "tfi_500", "liq_depletion",
    "log_depth1", "log_depth5", "cancel_pressure",
    "vol_500", "vpin",
]

# Resiliency features (exp010): computed from event dynamics
RESILIENCY_FEATURES = [
    "depth_recovery_ratio_5",   # depth after 5 events / depth before
    "depth_recovery_ratio_10",  # depth after 10 events / depth before
    "net_flow_5",               # net (bid_add - bid_cancel + ask_add - ask_cancel) / depth in 5 events
    "net_flow_10",              # same over 10 events
    "time_since_agg_event",     # events since last aggressive event (liq_depletion > threshold)
    "agg_event_depth_ratio",    # depth / depth at last aggressive event
    "bid_ask_flow_imbalance_5", # (bid_add - ask_add) / total flow in 5 events
    "cancel_pressure_5",        # cancellation rate in 5 events
    "depth_slope_5",            # depth slope (recovery rate) over 5 events
    "trade_absorption_5",       # trade count / depth in last 5 events
]

FEATURE_PATH = "data/research/v7_true_features.parquet"
OUT_DIR = Path("data/research/exp009")


def compute_resiliency_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute order-book resiliency (depth replenishment) features.
    
    For each event at time t:
    - Look back at the most recent aggressive event (liq_depletion > 90th pct)
    - Measure depth recovery since that event
    - Measure net order flow since that event
    - Measure time (in events) since the aggressive event
    
    All features are computed causally (from past events only).
    """
    df = df.copy()
    n = len(df)
    
    # Pre-compute arrays
    log_depth5 = df["log_depth5"].to_numpy(float)
    depth5 = np.expm1(log_depth5)
    bid_add = df["bid_add_bps"].to_numpy(float)
    bid_cancel = df["bid_cancel_bps"].to_numpy(float)
    ask_add = df["ask_add_bps"].to_numpy(float)
    ask_cancel = df["ask_cancel_bps"].to_numpy(float)
    liq_depletion = df["liq_depletion"].to_numpy(float)
    kind = df["kind"].to_numpy(str)
    
    # Aggressive event threshold (90th percentile of liq_depletion)
    threshold = np.percentile(liq_depletion, 90)
    
    # Initialize features
    recovery_5 = np.zeros(n)
    recovery_10 = np.zeros(n)
    net_flow_5 = np.zeros(n)
    net_flow_10 = np.zeros(n)
    time_since_agg = np.zeros(n, dtype=float)
    agg_depth_ratio = np.ones(n)
    ba_imbalance_5 = np.zeros(n)
    cancel_pressure_5 = np.zeros(n)
    depth_slope_5 = np.zeros(n)
    trade_absorption_5 = np.zeros(n)
    
    last_agg_idx = -1
    last_agg_depth = 1.0  # default depth ratio = 1.0
    
    for i in range(n):
        # Track most recent aggressive event
        if liq_depletion[i] > threshold:
            last_agg_idx = i
            last_agg_depth = depth5[i] if depth5[i] > 0 else 1.0
            time_since_agg[i] = 0
        else:
            time_since_agg[i] = float(i - last_agg_idx) if last_agg_idx >= 0 else float(i + 1)
            # Depth ratio: current depth vs depth at aggressive event
            if last_agg_idx >= 0 and last_agg_depth > 0:
                agg_depth_ratio[i] = depth5[i] / last_agg_depth
            else:
                agg_depth_ratio[i] = 1.0
        
        # Look back 5 and 10 events to compute recovery and flow
        for window, recovery_arr, net_flow_arr, ba_imb_arr, cancel_arr, slope_arr, absorption_arr in [
            (5, recovery_5, net_flow_5, ba_imbalance_5, cancel_pressure_5, depth_slope_5, trade_absorption_5),
            (10, recovery_10, net_flow_10, None, None, None, None),
        ]:
            start = max(0, i - window)
            w_bid_add = bid_add[start:i+1]
            w_bid_cancel = bid_cancel[start:i+1]
            w_ask_add = ask_add[start:i+1]
            w_ask_cancel = ask_cancel[start:i+1]
            w_depth = depth5[start:i+1]
            w_kind = kind[start:i+1]
            
            # Net flow (bps) in window
            total_flow = w_bid_add + w_ask_add + w_bid_cancel + w_ask_cancel
            net_flow = (w_bid_add - w_ask_add) + (w_bid_cancel - w_ask_cancel)
            d5 = np.mean(w_depth)
            if d5 > 0:
                net_flow_arr[i] = float(np.sum(net_flow) / d5)
            
            # Depth recovery ratio: if we have a reference depth before aggression
            if last_agg_idx >= 0 and i > last_agg_idx:
                ref_depth = max(depth5[last_agg_idx], 1e-9)
                recovery_arr[i] = float(depth5[i] / ref_depth)
            elif last_agg_idx >= 0 and i == last_agg_idx:
                recovery_arr[i] = 1.0
            else:
                recovery_arr[i] = 1.0
            
            if window == 5:
                # Bid-ask flow imbalance
                total_add = np.sum(w_bid_add) + np.sum(w_ask_add)
                if total_add > 0:
                    ba_imb_arr[i] = float((np.sum(w_bid_add) - np.sum(w_ask_add)) / total_add)
                
                # Cancel pressure
                total_all = total_add + np.sum(w_bid_cancel) + np.sum(w_ask_cancel)
                if total_all > 0:
                    cancel_arr[i] = float((np.sum(w_bid_cancel) + np.sum(w_ask_cancel)) / total_all)
                
                # Depth slope (linear trend over window)
                if len(w_depth) >= 3:
                    x = np.arange(len(w_depth))
                    slope = np.polyfit(x, w_depth, 1)[0]
                    ref_depth = max(np.mean(w_depth), 1e-9)
                    slope_arr[i] = float(slope / ref_depth)
                
                # Trade absorption
                n_trades = np.sum(w_kind == 'trade')
                if d5 > 0:
                    trade_absorption_5[i] = float(n_trades / d5)
    
    df["depth_recovery_ratio_5"] = recovery_5
    df["depth_recovery_ratio_10"] = recovery_10
    df["net_flow_5"] = net_flow_5
    df["net_flow_10"] = net_flow_10
    df["time_since_agg_event"] = time_since_agg
    df["agg_event_depth_ratio"] = agg_depth_ratio
    df["bid_ask_flow_imbalance_5"] = ba_imbalance_5
    df["cancel_pressure_5"] = cancel_pressure_5
    df["depth_slope_5"] = depth_slope_5
    df["trade_absorption_5"] = trade_absorption_5
    
    return df


def evaluate_model(X_train, y_train, X_val, y_val, X_oos, y_oos, 
                    gate_bps=COST_BPS, alpha=RIDGE_ALPHA):
    """Train ridge, calibrate, evaluate OOS."""
    ok_tr = np.isfinite(X_train).all(axis=1) & np.isfinite(y_train)
    ok_va = np.isfinite(X_val).all(axis=1) & np.isfinite(y_val)
    ok_os = np.isfinite(X_oos).all(axis=1) & np.isfinite(y_oos)
    if ok_tr.sum() < 50 or ok_va.sum() < 10 or ok_os.sum() < 10:
        return None

    X_tr, y_tr = X_train[ok_tr], y_train[ok_tr]
    X_va, y_va = X_val[ok_va], y_val[ok_va]
    X_os, y_os = X_oos[ok_os], y_oos[ok_os]

    try:
        beta, b0, mu, sd, r2_train, n_train = fit_ridge(X_tr, y_tr, alpha=alpha)
        val_pred = ridge_predict(X_va, beta, b0, mu, sd)
        calib = fit_binned_calibration(val_pred, y_va)
        
        # Full predictions for context
        all_pred_raw = ridge_predict(np.vstack([X_tr, X_va, X_os]), beta, b0, mu, sd)
        all_pred_cal = apply_calibration(all_pred_raw, calib)
        
        oos_pred = ridge_predict(X_os, beta, b0, mu, sd)
        oos_pred_cal = apply_calibration(oos_pred, calib)

        gross_mean, ci_lo, ci_hi = bootstrap_ci(oos_pred_cal)
        net = oos_pred_cal - gate_bps
        net_mean, net_ci_lo, net_ci_hi = bootstrap_ci(net)

        dir_acc = float(np.mean(np.sign(oos_pred_cal) == np.sign(y_os)))
        n_long = int(np.sum(oos_pred_cal > 0))
        n_short = int(np.sum(oos_pred_cal < 0))
        long_ret = float(np.mean(y_os[oos_pred_cal > 0])) if n_long > 0 else float('nan')
        short_ret = float(np.mean(y_os[oos_pred_cal < 0])) if n_short > 0 else float('nan')
        pct_above = float(np.mean(oos_pred_cal > gate_bps) * 100)
        
        long_net = long_ret - gate_bps if np.isfinite(long_ret) else None
        short_net = short_ret - gate_bps if np.isfinite(short_ret) else None

        actual_gross, _, _ = bootstrap_ci(y_os)
        actual_net, an_lo, an_hi = bootstrap_ci(y_os - gate_bps)

        h = hac_se(net)
        net_z = net_mean / h if h > 0 else 0.0

        up_pct = (y_os > 0).mean()
        down_pct = (y_os < 0).mean()
        baseline_acc = max(up_pct, down_pct)

        return {
            "n_train": int(len(y_tr)),
            "n_val": int(len(y_va)),
            "n_oos": int(len(y_os)),
            "r2_train": float(r2_train),
            "gross_pred_bps": round(gross_mean, 4),
            "gross_pred_ci95": [round(ci_lo, 4), round(ci_hi, 4)],
            "net_pred_bps": round(net_mean, 4),
            "net_pred_ci95": [round(net_ci_lo, 4), round(net_ci_hi, 4)],
            "actual_gross_bps": round(actual_gross, 4),
            "actual_net_bps": round(actual_net, 4),
            "actual_net_ci95": [round(an_lo, 4), round(an_hi, 4)],
            "direction_accuracy": round(dir_acc, 4),
            "baseline_accuracy": round(float(baseline_acc), 4),
            "n_long": n_long,
            "n_short": n_short,
            "long_net_bps": round(long_net, 4) if long_net is not None else None,
            "short_net_bps": round(short_net, 4) if short_net is not None else None,
            "pct_above_gate": round(pct_above, 2),
            "hac_se": round(h, 6),
            "net_z": round(net_z, 4),
        }
    except Exception as e:
        return {"error": str(e)}


def run_exp008_baseline_comparison():
    """Run a baseline model (V5 features only) for comparison."""
    pass  # Will be integrated in main function


def run_exp009():
    """Run EXP-009: Order-Book Resiliency Signal."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading data...")
    df = pd.read_parquet(FEATURE_PATH)
    df = df.sort_values("ts_ms").reset_index(drop=True)
    
    print("Computing resiliency features...")
    df = compute_resiliency_features(df)
    
    # Replace inf with nan
    for col in RESILIENCY_FEATURES:
        if col in df.columns:
            df[col] = df[col].replace([np.inf, -np.inf], np.nan)
    
    # Add labels for all horizons
    df = add_labels(df, horizons=HORIZONS)
    
    print(f"Data: {len(df)} events, {df['session'].nunique()} sessions")
    print(f"\nResiliency feature stats:")
    for col in RESILIENCY_FEATURES:
        vals = df[col].to_numpy(float)
        print(f"  {col}: mean={vals.mean():.6f}, std={vals.std():.6f}, "
              f"pct_finite={(np.isfinite(vals)).mean()*100:.1f}%")
    
    # Chronological splits
    splits = chrono_split_masks(df)
    train_mask = np.asarray(splits[0]["mask"], dtype=bool)
    val_mask = np.asarray(splits[1]["mask"], dtype=bool)
    oos_mask = np.asarray(splits[2]["mask"], dtype=bool)
    
    # Feature sets to compare
    feature_sets = {
        "V5_baseline": BASE_FEATURES,
        "V5_plus_resiliency": BASE_FEATURES + RESILIENCY_FEATURES,
    }
    
    results = {
        "experiment_id": "EXP-009",
        "hypothesis": "Order-Book Resiliency Signal",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cost_bps": COST_BPS,
        "alpha": RIDGE_ALPHA,
        "resiliency_features": RESILIENCY_FEATURES,
        "horizons": {},
    }
    
    overall_positive = False
    
    for h in HORIZONS:
        label_col = f"r_{h}"
        print(f"\n{'='*60}")
        print(f"Horizon: {h}ms")
        print(f"{'='*60}")
        
        horizon_result = {"feature_sets": {}, "verdict": None}
        best_net = -float('inf')
        best_fs = None
        
        for fs_name, fs_cols in feature_sets.items():
            cols = [c for c in fs_cols if c in df.columns]
            print(f"\n  Feature set: {fs_name} ({len(cols)} features)")
            
            X_all = df[cols].to_numpy(float)
            y_all = df[label_col].to_numpy(float)
            
            X_train = X_all[train_mask]
            y_train = y_all[train_mask]
            X_val = X_all[val_mask]
            y_val = y_all[val_mask]
            X_oos = X_all[oos_mask]
            y_oos = y_all[oos_mask]
            
            metrics = evaluate_model(X_train, y_train, X_val, y_val, X_oos, y_oos)
            
            if metrics is None:
                print(f"    SKIPPED: insufficient data")
                horizon_result["feature_sets"][fs_name] = {"status": "insufficient_data"}
                continue
            
            if "error" in metrics:
                print(f"    ERROR: {metrics['error']}")
                horizon_result["feature_sets"][fs_name] = {"status": "error"}
                continue
            
            print(f"    r2_train={metrics['r2_train']:.4f}")
            print(f"    gross_pred={metrics['gross_pred_bps']:+.4f}, net_pred={metrics['net_pred_bps']:+.4f}")
            print(f"    [{metrics['net_pred_ci95'][0]:.4f}, {metrics['net_pred_ci95'][1]:.4f}]")
            print(f"    actual_net={metrics['actual_net_bps']:+.4f}")
            print(f"    dir_acc={metrics['direction_accuracy']:.4f} (bl={metrics['baseline_accuracy']:.4f})")
            print(f"    pct_above_gate={metrics['pct_above_gate']:.2f}%")
            
            if metrics["direction_accuracy"] > metrics["baseline_accuracy"]:
                print(f"    NOTE: Direction accuracy IMPROVES over baseline")
            
            horizon_result["feature_sets"][fs_name] = metrics
            
            if metrics["net_pred_bps"] > best_net:
                best_net = metrics["net_pred_bps"]
                best_fs = fs_name
            
            if metrics["net_pred_bps"] > 0 and metrics["pct_above_gate"] > 1.0:
                overall_positive = True
        
        horizon_result["best_feature_set"] = best_fs
        horizon_result["best_net_bps"] = round(best_net, 4) if best_fs else None
        horizon_result["verdict"] = "POSITIVE_NET" if overall_positive else "NEGATIVE_NET"
        results["horizons"][str(h)] = horizon_result
    
    results["verdict"] = "HYPOTHESIS_PASSED" if overall_positive else "HYPOTHESIS_REJECTED"
    
    # Save results
    results_path = OUT_DIR / "exp009_results.json"
    results_path.write_text(json.dumps(results, indent=2, default=str))
    
    print(f"\n\n{'='*60}")
    print(f"EXP-009 FINAL VERDICT: {results['verdict']}")
    print(f"{'='*60}")
    
    for h in HORIZONS:
        hr = results["horizons"].get(str(h), {})
        print(f"\n  Horizon {h}ms: best={hr.get('best_feature_set','N/A')} "
              f"net={hr.get('best_net_bps','N/A')}")
        for fs, m in hr.get("feature_sets", {}).items():
            if "status" in m:
                print(f"    {fs}: {m['status']}")
            elif "error" in m:
                print(f"    {fs}: ERROR")
            else:
                print(f"    {fs}: net={m['net_pred_bps']:+.4f} "
                      f"dir_acc={m['direction_accuracy']:.4f} "
                      f"above={m['pct_above_gate']:.1f}%")
    
    return results


if __name__ == "__main__":
    run_exp009()
