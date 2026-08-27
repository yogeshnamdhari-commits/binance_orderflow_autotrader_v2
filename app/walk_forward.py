"""Walk-forward validation with purging and embargoing.

Implements:
- Chronological walk-forward splits
- Purging: remove train samples whose labels overlap with test
- Embargo: add gap after train to prevent leakage through overlapping windows
- Multiple window configurations for robustness

Research basis:
  - Bailey & Lopez de Prado (2014): purged k-fold cross-validation
  - De Prado (2018): Advances in Financial ML — embargoing

Usage:
    python -m app.walk_forward --features data/research/v7_true_features.parquet
"""

import json
import argparse
from pathlib import Path
from typing import List, Tuple, Dict, Optional

import numpy as np
import pandas as pd

from app.v3_labels import add_labels
from app.v3_model import chrono_split_masks


def purged_split(ts: np.ndarray, labels_start: np.ndarray, labels_end: np.ndarray,
                 train_frac: float = 0.7, val_frac: float = 0.15,
                 embargo_frac: float = 0.01) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Create purged and embargoed chronological split.
    
    Args:
        ts: event timestamps (int64 ms)
        labels_start: start of label window for each event
        labels_end: end of label window for each event
        train_frac: fraction for training
        val_frac: fraction for validation
        embargo_frac: fraction of data to use as embargo gap
    
    Returns:
        (train_mask, val_mask, oos_mask) boolean arrays
    """
    n = len(ts)
    cut1 = np.quantile(ts, train_frac)
    cut2 = np.quantile(ts, train_frac + val_frac)
    
    # Raw splits
    train_mask = ts <= cut1
    val_mask = (ts > cut1) & (ts <= cut2)
    oos_mask = ts > cut2
    
    # Purge: remove train samples whose labels extend into val/test
    for i in np.where(train_mask)[0]:
        if labels_end[i] > cut1:
            train_mask[i] = False
    
    # Purge: remove val samples whose labels extend into test
    for i in np.where(val_mask)[0]:
        if labels_end[i] > cut2:
            val_mask[i] = False
    
    # Embargo: add gap after train to prevent leakage
    embargo_cut = cut1 + (ts.max() - ts.min()) * embargo_frac
    val_mask = val_mask & (ts > embargo_cut)
    oos_mask = oos_mask & (ts > embargo_cut)
    
    return train_mask, val_mask, oos_mask


def walk_forward_splits(ts: np.ndarray, n_windows: int = 5,
                       min_train_frac: float = 0.3) -> List[Tuple[np.ndarray, np.ndarray]]:
    """Generate walk-forward train/test window pairs.
    
    Each window: train on [0, cut], test on [cut, cut + test_size]
    Windows slide forward through the data.
    
    Args:
        ts: event timestamps (int64 ms)
        n_windows: number of walk-forward windows
        min_train_frac: minimum fraction for training set
    
    Returns:
        List of (train_mask, test_mask) tuples
    """
    n = len(ts)
    windows = []
    
    for w in range(n_windows):
        # Slide the cut point forward
        cut_frac = min_train_frac + (1 - min_train_frac) * w / max(n_windows - 1, 1)
        test_frac = (1 - cut_frac) / 2  # Test is half of remaining data
        
        cut_train = np.quantile(ts, cut_frac)
        cut_test = np.quantile(ts, cut_frac + test_frac)
        
        train_mask = ts <= cut_train
        test_mask = (ts > cut_train) & (ts <= cut_test)
        
        windows.append((train_mask, test_mask))
    
    return windows


def compute_label_windows(df: pd.DataFrame, horizon_ms: int = 500) -> Tuple[np.ndarray, np.ndarray]:
    """Compute label start and end times for each event.
    
    For a forward return at horizon h:
      label_start = ts
      label_end = ts + h
    """
    ts = df["ts_ms"].to_numpy(dtype=np.int64)
    labels_start = ts
    labels_end = ts + horizon_ms
    return labels_start, labels_end


def run_walk_forward_validation(feature_path: str | Path,
                                out_dir: str | Path,
                                horizon_ms: int = 500,
                                n_windows: int = 5) -> Dict:
    """Run walk-forward validation with purging and embargoing."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    df = pd.read_parquet(feature_path)
    df = add_labels(df, horizons=(horizon_ms,))
    label_col = f"r_{horizon_ms}"
    
    ts = df["ts_ms"].to_numpy(dtype=np.int64)
    y = df[label_col].to_numpy(float)
    
    # Compute label windows for purging
    labels_start, labels_end = compute_label_windows(df, horizon_ms)
    
    # Features
    from app.v7_model import V5_FEATURES, fit_ridge, ridge_predict
    from app.v7_model import fit_binned_calibration, apply_calibration, validate_model
    
    # V7 feature groups (from v7_final_validation.py)
    V7_MULTI_LEVEL_OFI = ["ofi_l2", "ofi_l3", "ofi_l4", "ofi_l5", "ofi_l6",
                          "ofi_l7", "ofi_l8", "ofi_l9", "ofi_l10",
                          "mlofi_weighted", "ofi_decay", "ofi_net_levels"]
    V7_QUEUE = ["qi_l2", "qi_l3", "qi_l5", "qi_l10", "qi_multi", "qi_slope", "qi_accel"]
    V7_MICROPRICE = ["mp_vel", "mp_reversion"]
    V7_TOXICITY = ["vpin", "kyle_lambda", "signed_vol_imbalance"]
    V7_STRUCTURE = ["depth_slope_levels", "depth_asymmetry"]
    V7_VOLATILITY = ["vol_ratio"]
    V7_INTERACTIONS = ["ofi_x_qi", "mlofi_x_spread"]
    
    V7_ALL_FEATURES = V5_FEATURES + V7_MULTI_LEVEL_OFI + V7_QUEUE + V7_MICROPRICE + V7_TOXICITY + V7_STRUCTURE + V7_VOLATILITY + V7_INTERACTIONS
    
    # Use V7 features that exist in the dataframe
    features = [f for f in V7_ALL_FEATURES if f in df.columns]
    X = df[features].to_numpy(float)
    
    # Filter finite
    finite = np.isfinite(X).all(axis=1) & np.isfinite(y)
    df = df.loc[finite].reset_index(drop=True)
    ts = ts[finite]
    y = y[finite]
    X = X[finite]
    labels_start = labels_start[finite]
    labels_end = labels_end[finite]
    
    results = {
        "horizon_ms": horizon_ms,
        "n_events": len(df),
        "n_features": len(features),
        "features_used": features,
    }
    
    # Standard chronological split (for comparison)
    splits = chrono_split_masks(df)
    train_mask = splits[0]["mask"]
    val_mask = splits[1]["mask"]
    oos_mask = splits[2]["mask"]
    
    # Fit on standard split
    X_train, y_train = X[train_mask], y[train_mask]
    X_val, y_val = X[val_mask], y[val_mask]
    
    beta, b0, mu, sd, r2, n = fit_ridge(X_train, y_train)
    val_pred = ridge_predict(X_val, beta, b0, mu, sd)
    calib = fit_binned_calibration(val_pred, y_val)
    all_pred = ridge_predict(X, beta, b0, mu, sd)
    all_pred_cal = apply_calibration(all_pred, calib)
    
    results["standard_split"] = validate_model(y, all_pred_cal, oos_mask)
    
    # Purged split
    train_purged, val_purged, oos_purged = purged_split(
        ts, labels_start, labels_end,
        train_frac=0.7, val_frac=0.15, embargo_frac=0.01
    )
    
    if train_purged.sum() > 100 and oos_purged.sum() > 50:
        beta_p, b0_p, mu_p, sd_p, r2_p, n_p = fit_ridge(X[train_purged], y[train_purged])
        val_pred_p = ridge_predict(X[val_purged], beta_p, b0_p, mu_p, sd_p)
        calib_p = fit_binned_calibration(val_pred_p, y[val_purged])
        all_pred_p = ridge_predict(X, beta_p, b0_p, mu_p, sd_p)
        all_pred_p_cal = apply_calibration(all_pred_p, calib_p)
        results["purged_split"] = validate_model(y, all_pred_p_cal, oos_purged)
        results["purged_split"]["n_train"] = int(train_purged.sum())
        results["purged_split"]["n_val"] = int(val_purged.sum())
        results["purged_split"]["n_oos"] = int(oos_purged.sum())
    
    # Walk-forward windows
    wf_windows = walk_forward_splits(ts, n_windows=n_windows)
    wf_results = []
    
    for w, (train_w, test_w) in enumerate(wf_windows):
        if train_w.sum() < 100 or test_w.sum() < 50:
            continue
        
        try:
            beta_w, b0_w, mu_w, sd_w, r2_w, n_w = fit_ridge(X[train_w], y[train_w])
            all_pred_w = ridge_predict(X, beta_w, b0_w, mu_w, sd_w)
            # No calibration for walk-forward (use raw predictions)
            wf_res = validate_model(y, all_pred_w, test_w)
            wf_res["window"] = w
            wf_res["n_train"] = int(train_w.sum())
            wf_res["n_test"] = int(test_w.sum())
            wf_results.append(wf_res)
        except Exception as e:
            wf_results.append({"window": w, "error": str(e)})
    
    results["walk_forward"] = wf_results
    
    # Save
    (out_dir / "walk_forward_validation.json").write_text(
        json.dumps(results, indent=2, default=str))
    
    return results


def print_walk_forward_report(results: Dict):
    """Print walk-forward validation report."""
    print("=" * 70)
    print("WALK-FORWARD VALIDATION REPORT")
    print("=" * 70)
    print(f"Horizon: {results['horizon_ms']} ms")
    print(f"Events: {results['n_events']}")
    print(f"Features: {results['n_features']}")
    
    if "standard_split" in results:
        r = results["standard_split"]
        print(f"\nStandard split: gross={r['gross_mean_bps']:+.4f}, "
              f"net={r['net_mean_bps']:+.4f}, verdict={r['verdict']}")
    
    if "purged_split" in results:
        r = results["purged_split"]
        print(f"Purged split:   gross={r['gross_mean_bps']:+.4f}, "
              f"net={r['net_mean_bps']:+.4f}, verdict={r['verdict']}")
    
    if "walk_forward" in results:
        print(f"\nWalk-forward windows:")
        for wf in results["walk_forward"]:
            if "error" in wf:
                print(f"  Window {wf['window']}: ERROR - {wf['error']}")
            else:
                print(f"  Window {wf['window']}: gross={wf['gross_mean_bps']:+.4f}, "
                      f"net={wf['net_mean_bps']:+.4f}, n_train={wf['n_train']}, "
                      f"n_test={wf['n_test']}")
    
    print("=" * 70)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", type=Path,
                    default=Path("data/research/v7_true_features.parquet"))
    ap.add_argument("--out", type=Path, default=Path("data/research/v7"))
    ap.add_argument("--horizon", type=int, default=500)
    ap.add_argument("--windows", type=int, default=5)
    a = ap.parse_args()
    
    results = run_walk_forward_validation(a.features, a.out, a.horizon, a.windows)
    print_walk_forward_report(results)
