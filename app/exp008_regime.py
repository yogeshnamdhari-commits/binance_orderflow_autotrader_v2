#!/usr/bin/env python3
"""EXP-008: Volatility-Regime Conditional Trading (REGIME).

Hypothesis:
  The directional signal from order-flow features is stronger in HIGH volatility
  regimes, where the signal-to-cost ratio improves because moves are larger.

  V5-V8 trained a single model on ALL data and found:
  - Gross signal: +0.02 to +0.10 bps (tiny but sometimes positive)
  - Net signal: -1.9 to -2.7 bps (killed by 2.0-2.5 bps maker fee)
  - 88% of 500ms returns are 0.0 bps

  EXP-008 tests whether conditioning on volatility regime can:
  1. Improve direction accuracy above baseline within the high-vol subset
  2. Increase trade frequency (|r| > cost) in high-vol regime
  3. Produce positive net expectancy on the traded subset

Falsification criteria (pre-registered):
  - If net expectancy is not positive in ANY regime at ANY horizon, reject
  - If direction accuracy does not improve in high-vol regime vs all-data, reject
  - If trade frequency < 1% in high-vol, reject

Research basis:
  - Cartea, Jaimungal & Penalva (2015): Market microstructure varies with volatility
  - Cont, Kukanov & Stoikov (2014): OFI predictive power is regime-dependent
  - Easley et al. (2012): VPIN and informed trading vary with volatility

Data required: v7_true_features.parquet (V5/V7 features)
Expected horizon: 30s (where P(|r|>2) ~9.5%)
Expected direction: HIGH vol regime should have better direction accuracy
Expected cost sensitivity: HIGH — 2.0 bps maker fee is the binding constraint
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

DIRECTION_FEATURES = [
    "tfi_500", "signed_vol_imbalance", "qi_l1", "di_l5", "mpd_bps",
    "ofi_l1", "ofi_norm_l1", "spread_bps", "cancel_pressure",
    "vol_500", "vol_2000", "liq_depletion", "vpin", "kyle_lambda",
    "depth_slope_bps", "log_depth5", "signed_vol_500", "log_event_rate",
]

FEATURE_PATH = "data/research/v7_true_features.parquet"
OUT_DIR = Path("data/research/exp008")


def compute_volatility_signal(df: pd.DataFrame) -> np.ndarray:
    """Compute composite volatility signal from multiple proxies."""
    n = len(df)
    mid = df["mid"].to_numpy(float)
    vol_500 = df["vol_500"].fillna(0).to_numpy(float)
    vol_2000 = df["vol_2000"].fillna(0).to_numpy(float)

    trailing_vol = np.zeros(n)
    for i in range(n):
        start = max(0, i - 50)
        m = mid[start:i + 1]
        m = m[m > 0]
        if len(m) >= 3:
            returns = np.diff(m) / m[:-1]
            trailing_vol[i] = np.std(returns) * 1e4
        else:
            trailing_vol[i] = 0.0

    vol_score = 0.4 * vol_500 + 0.3 * vol_2000 + 0.3 * trailing_vol
    return vol_score


def assign_vol_regime(vol_score: np.ndarray) -> np.ndarray:
    """Assign vol_regime: zero_vol, low_vol, med_vol, high_vol."""
    regimes = np.full(len(vol_score), "zero_vol", dtype=object)
    nonzero = vol_score > 0
    if nonzero.sum() < 30:
        q33 = np.percentile(vol_score, 33.3)
        q67 = np.percentile(vol_score, 66.7)
        regimes[vol_score < q33] = "low_vol"
        regimes[(vol_score >= q33) & (vol_score < q67)] = "med_vol"
        regimes[vol_score >= q67] = "high_vol"
    else:
        q33 = np.percentile(vol_score[nonzero], 33.3)
        q67 = np.percentile(vol_score[nonzero], 66.7)
        nz = vol_score[nonzero]
        regimes[nonzero] = np.where(
            nz < q33, "low_vol",
            np.where(nz < q67, "med_vol", "high_vol")
        )
    return regimes


def evaluate_regime(X_train, y_train, X_val, y_val, X_oos, y_oos, alpha=RIDGE_ALPHA):
    """Train ridge + binned calibration, return OOS metrics."""
    if len(y_train) < 50 or len(y_val) < 10 or len(y_oos) < 10:
        return None

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
        oos_pred = ridge_predict(X_os, beta, b0, mu, sd)
        oos_pred_cal = apply_calibration(oos_pred, calib)

        gross_mean, ci_lo, ci_hi = bootstrap_ci(oos_pred_cal)
        net = oos_pred_cal - COST_BPS
        net_mean, net_ci_lo, net_ci_hi = bootstrap_ci(net)

        dir_acc = float(np.mean(np.sign(oos_pred_cal) == np.sign(y_os)))
        n_long = int(np.sum(oos_pred_cal > 0))
        n_short = int(np.sum(oos_pred_cal < 0))
        long_ret = float(np.mean(y_os[oos_pred_cal > 0])) if n_long > 0 else float('nan')
        short_ret = float(np.mean(y_os[oos_pred_cal < 0])) if n_short > 0 else float('nan')
        pct_above = float(np.mean(oos_pred_cal > COST_BPS) * 100)

        long_net = long_ret - COST_BPS if np.isfinite(long_ret) else None
        short_net = short_ret - COST_BPS if np.isfinite(short_ret) else None

        actual_gross, _, _ = bootstrap_ci(y_os)
        actual_net_mean, actual_net_lo, actual_net_hi = bootstrap_ci(y_os - COST_BPS)

        h = hac_se(net)
        net_z = net_mean / h if h > 0 else 0.0

        # Baseline: predict majority sign
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
            "actual_net_bps": round(actual_net_mean, 4),
            "actual_net_ci95": [round(actual_net_lo, 4), round(actual_net_hi, 4)],
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


def run_exp008():
    """Run EXP-008: Volatility-regime conditional trading at multiple horizons."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(FEATURE_PATH)
    df = df.sort_values("ts_ms").reset_index(drop=True)

    # Add labels for ALL horizons at once
    df = add_labels(df, horizons=HORIZONS)

    # Compute volatility signal and regimes
    vol_score = compute_volatility_signal(df)
    df["vol_score"] = vol_score
    df["vol_regime"] = assign_vol_regime(vol_score)

    print(f"Loaded {len(df)} events, {df['session'].nunique()} sessions")
    print("\n=== Volatility Regime Distribution ===")
    print(df["vol_regime"].value_counts())
    print(f"\nVol score: mean={vol_score.mean():.4f}, std={vol_score.std():.4f}, max={vol_score.max():.4f}")

    # Global chronological splits
    splits = chrono_split_masks(df)
    train_mask = np.asarray(splits[0]["mask"], dtype=bool)
    val_mask = np.asarray(splits[1]["mask"], dtype=bool)
    oos_mask = np.asarray(splits[2]["mask"], dtype=bool)

    feature_cols = [c for c in DIRECTION_FEATURES if c in df.columns]
    print(f"\nDirection features ({len(feature_cols)}): {feature_cols}")

    results = {
        "experiment_id": "EXP-008",
        "hypothesis": "Volatility-Regime Conditional Trading",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cost_bps": COST_BPS,
        "alpha": RIDGE_ALPHA,
        "direction_features": feature_cols,
        "horizons": {},
    }

    overall_positive = False

    for h in HORIZONS:
        label_col = f"r_{h}"
        print(f"\n{'='*60}")
        print(f"Horizon: {h}ms")
        print(f"{'='*60}")

        horizon_result = {"regimes": {}, "best_regime": None, "verdict": None}
        best_net = -float('inf')
        best_regime = None
        any_positive_horizon = False

        for regime in ["zero_vol", "low_vol", "med_vol", "high_vol"]:
            regime_mask = (df["vol_regime"] == regime).to_numpy(bool)
            r_train = train_mask & regime_mask
            r_val = val_mask & regime_mask
            r_oos = oos_mask & regime_mask

            n_tr = int(r_train.sum())
            n_va = int(r_val.sum())
            n_os = int(r_oos.sum())

            print(f"\n  Regime: {regime} | train={n_tr} val={n_va} oos={n_os}")

            if n_tr < 50 or n_va < 20 or n_os < 20:
                print(f"    SKIPPED: insufficient data")
                horizon_result["regimes"][regime] = {
                    "n_train": n_tr, "n_val": n_va, "n_oos": n_os,
                    "status": "insufficient_data"
                }
                continue

            X_all = df.loc[regime_mask, feature_cols].to_numpy(float)
            y_all = df.loc[regime_mask, label_col].to_numpy(float)

            X_train = X_all[r_train[regime_mask]]
            y_train = y_all[r_train[regime_mask]]
            X_val = X_all[r_val[regime_mask]]
            y_val = y_all[r_val[regime_mask]]
            X_oos = X_all[r_oos[regime_mask]]
            y_oos = y_all[r_oos[regime_mask]]

            metrics = evaluate_regime(X_train, y_train, X_val, y_val, X_oos, y_oos)

            if metrics is None:
                print(f"    SKIPPED: insufficient finite data")
                horizon_result["regimes"][regime] = {
                    "n_train": n_tr, "n_val": n_va, "n_oos": n_os,
                    "status": "insufficient_finite"
                }
                continue

            if "error" in metrics:
                print(f"    ERROR: {metrics['error']}")
                horizon_result["regimes"][regime] = {
                    "n_train": n_tr, "n_val": n_va, "n_oos": n_os,
                    "status": f"error"
                }
                continue

            print(f"    r2_train={metrics['r2_train']:.4f}")
            print(f"    gross_pred={metrics['gross_pred_bps']:+.4f}, "
                  f"net_pred={metrics['net_pred_bps']:+.4f} "
                  f"[{metrics['net_pred_ci95'][0]:.4f}, {metrics['net_pred_ci95'][1]:.4f}]")
            print(f"    actual_gross={metrics['actual_gross_bps']:+.4f}, "
                  f"actual_net={metrics['actual_net_bps']:+.4f}")
            print(f"    dir_acc={metrics['direction_accuracy']:.4f} "
                  f"(baseline={metrics['baseline_accuracy']:.4f}), "
                  f"above_gate={metrics['pct_above_gate']:.2f}%, "
                  f"z={metrics['net_z']:.4f}")

            horizon_result["regimes"][regime] = metrics

            if metrics["net_pred_bps"] > best_net:
                best_net = metrics["net_pred_bps"]
                best_regime = regime

            if metrics["net_pred_bps"] > 0 and metrics["pct_above_gate"] > 1.0:
                any_positive_horizon = True

            if metrics["direction_accuracy"] > metrics["baseline_accuracy"]:
                print(f"    NOTE: Direction accuracy IMPROVES over baseline")

        horizon_result["best_regime"] = best_regime
        horizon_result["best_net_bps"] = round(best_net, 4) if best_regime else None
        horizon_result["verdict"] = "POSITIVE_NET" if any_positive_horizon else "NEGATIVE_NET"
        results["horizons"][str(h)] = horizon_result

        if any_positive_horizon:
            overall_positive = True

    results["verdict"] = "HYPOTHESIS_PASSED_CONDITIONALLY" if overall_positive else "HYPOTHESIS_REJECTED"
    results["vol_regime_counts"] = df["vol_regime"].value_counts().to_dict()

    results_path = OUT_DIR / "exp008_results.json"
    results_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"\n\nResults saved to {results_path}")
    print(f"\n{'='*60}")
    print(f"EXP-008 FINAL VERDICT: {results['verdict']}")
    print(f"{'='*60}")

    for h in HORIZONS:
        hr = results["horizons"].get(str(h), {})
        print(f"\n  Horizon {h}ms: best={hr.get('best_regime','N/A')} "
              f"net={hr.get('best_net_bps','N/A')} verdict={hr.get('verdict','N/A')}")
        for reg, m in hr.get("regimes", {}).items():
            if "status" in m:
                print(f"    {reg}: {m['status']}")
            elif "error" in m:
                print(f"    {reg}: ERROR")
            else:
                print(f"    {reg}: net={m['net_pred_bps']:+.4f} "
                      f"[{m['net_pred_ci95'][0]:.4f}, {m['net_pred_ci95'][1]:.4f}] "
                      f"dir_acc={m['direction_accuracy']:.4f} "
                      f"bl={m['baseline_accuracy']:.4f} "
                      f"above={m['pct_above_gate']:.1f}%")

    return results


if __name__ == "__main__":
    run_exp008()
