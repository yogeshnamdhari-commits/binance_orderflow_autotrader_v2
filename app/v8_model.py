"""V8 Model: Direction-Magnitude Decomposition with Selective Trading.

Pre-registered hypothesis (EXP-005):
  Stage 1: Predict direction using order-flow features (logistic)
  Stage 2: Predict magnitude using toxicity/liquidity features (ridge on |r|)
  Stage 3: Trade only when P(correct) x E[|r|] > cost

Research basis:
  - Cont, Kukanov & Stoikov (2014): OFI predicts direction
  - Easley, LdP & O'Hara (2012): VPIN predicts magnitude
  - Cartea, Donnelly & Jaimungal (2015): Selective trading / market impact
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Tuple

from app.v3_labels import add_labels
from app.v3_model import chrono_split_masks, SPLIT_FRACTIONS

# Pre-registered features (defined before seeing results)
DIRECTION_FEATURES = ["tfi_500", "signed_vol_imbalance", "qi_l1", "di_l5", "mpd_bps"]
MAGNITUDE_FEATURES = ["vpin", "liq_depletion", "vol_500", "depth_slope_bps", "spread_bps"]

# Pre-registered cost model
MAKER_FEE_BPS = 2.0
SAFETY_MARGIN_BPS = 0.5
TOTAL_COST_BPS = MAKER_FEE_BPS + SAFETY_MARGIN_BPS  # 2.5 bps

# Pre-registered decision gate thresholds
MIN_DIRECTION_CONFIDENCE = 0.55
MIN_MAGNITUDE_BPS = 2.0
MAX_SPREAD_BPS = 3.0
MIN_TRADE_PCT = 5.0

PRIMARY_HORIZON = 500


def prepare_data(feature_path: str | Path, horizon_ms: int = PRIMARY_HORIZON):
    """Load data, add labels, return with splits."""
    df = pd.read_parquet(feature_path)
    df = add_labels(df, horizons=(horizon_ms,))
    label_col = f"r_{horizon_ms}"
    
    # Filter valid rows
    all_features = DIRECTION_FEATURES + MAGNITUDE_FEATURES + [label_col, "mid", "spread_bps", "regime"]
    mask = (
        df["mid"].notna() & (df["mid"] > 0) &
        df["spread_bps"].notna() & (df["spread_bps"] > 0) &
        df[all_features].notna().all(axis=1)
    )
    df = df.loc[mask].reset_index(drop=True)
    
    # Splits
    splits = chrono_split_masks(df)
    train_mask = splits[0]["mask"]
    val_mask = splits[1]["mask"]
    oos_mask = splits[2]["mask"]
    
    return df, train_mask, val_mask, oos_mask


def fit_logistic(X, y_binary, alpha=0.01, max_iter=1000):
    """Fit logistic regression using gradient descent."""
    n, d = X.shape
    X_bias = np.column_stack([np.ones(n), X])
    w = np.zeros(d + 1)
    
    for _ in range(max_iter):
        z = X_bias @ w
        p = 1 / (1 + np.exp(-np.clip(z, -500, 500)))
        grad = X_bias.T @ (p - y_binary) / n
        grad[1:] += alpha * w[1:]  # L2 regularization (no bias penalty)
        hess = (X_bias.T * (p * (1 - p))) @ X_bias / n
        hess[1:, 1:] += alpha * np.eye(d)
        try:
            delta = np.linalg.solve(hess, grad)
            w -= delta
            if np.max(np.abs(delta)) < 1e-6:
                break
        except np.linalg.LinAlgError:
            break
    
    return w


def logistic_predict_prob(X, w):
    """Predict P(y=1) using logistic model."""
    X_bias = np.column_stack([np.ones(len(X)), X])
    z = X_bias @ w
    return 1 / (1 + np.exp(-np.clip(z, -500, 500)))


def fit_ridge(X, y, alpha=0.05):
    """Closed-form ridge regression."""
    mus = np.nanmean(X, axis=0)
    sds = np.nanstd(X, axis=0)
    sds = np.where(sds < 1e-12, 1.0, sds)
    Z = (X - mus) / sds
    ok = np.isfinite(Z).all(axis=1) & np.isfinite(y)
    if ok.sum() < 50:
        raise ValueError(f"Insufficient train rows: {ok.sum()}")
    A = Z[ok].T @ Z[ok] + alpha * np.eye(Z.shape[1])
    b = Z[ok].T @ y[ok]
    beta = np.linalg.solve(A, b)
    b0 = float(y[ok].mean() - beta @ np.nanmean(Z[ok], axis=0))
    return beta, b0, mus, sds, int(ok.sum())


def ridge_predict(X, beta, b0, mus, sds):
    """Predict using ridge coefficients."""
    Z = (X - mus) / sds
    Z = np.where(np.isfinite(Z), Z, 0.0)
    return np.maximum(0, b0 + Z @ beta)  # Magnitude is non-negative


def bootstrap_ci(values, n_boot=2000, alpha=0.05):
    """Bootstrap confidence interval for mean."""
    values = values[np.isfinite(values)]
    if len(values) < 10:
        return float(np.mean(values)), float('nan'), float('nan')
    rng = np.random.RandomState(42)
    boot_means = np.array([
        np.mean(rng.choice(values, size=len(values), replace=True))
        for _ in range(n_boot)
    ])
    return float(np.mean(values)), float(np.percentile(boot_means, 100 * alpha / 2)), \
           float(np.percentile(boot_means, 100 * (1 - alpha / 2)))


def run_v8_validation(feature_path: str | Path,
                      out_dir: str | Path,
                      horizon_ms: int = PRIMARY_HORIZON) -> Dict:
    """Run full V8 two-stage validation."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Prepare data
    df, train_mask, val_mask, oos_mask = prepare_data(feature_path, horizon_ms)
    label_col = f"r_{horizon_ms}"
    
    y_all = df[label_col].to_numpy(float)
    dir_all = (y_all > 0).astype(float)  # Binary direction
    mag_all = np.abs(y_all)  # Magnitude
    
    # Features
    X_dir = df[DIRECTION_FEATURES].to_numpy(float)
    X_mag = df[MAGNITUDE_FEATURES].to_numpy(float)
    
    results = {
        "experiment_id": "EXP-005",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hypothesis": "Direction-Magnitude Decomposition with Selective Trading",
        "horizon_ms": horizon_ms,
        "n_events": len(df),
        "n_train": int(train_mask.sum()),
        "n_val": int(val_mask.sum()),
        "n_oos": int(oos_mask.sum()),
        "direction_features": DIRECTION_FEATURES,
        "magnitude_features": MAGNITUDE_FEATURES,
        "cost_bps": TOTAL_COST_BPS,
    }
    
    # === Stage 1: Direction Model ===
    X_dir_train = X_dir[train_mask]
    y_dir_train = dir_all[train_mask]
    
    # Standardize on train
    dir_mu = np.nanmean(X_dir_train, axis=0)
    dir_sd = np.nanstd(X_dir_train, axis=0)
    dir_sd = np.where(dir_sd < 1e-12, 1.0, dir_sd)
    X_dir_train_z = (X_dir_train - dir_mu) / dir_sd
    X_dir_all_z = (X_dir - dir_mu) / dir_sd
    
    # Fit logistic
    w_dir = fit_logistic(X_dir_train_z, y_dir_train)
    
    # Predict probabilities
    p_up = logistic_predict_prob(X_dir_all_z, w_dir)
    p_correct_dir = np.maximum(p_up, 1 - p_up)  # Confidence in predicted direction
    
    # Direction accuracy on OOS
    dir_pred = (p_up > 0.5).astype(float)
    dir_acc_oos = np.mean(dir_pred[oos_mask] == dir_all[oos_mask])
    
    results["stage1_direction"] = {
        "oos_accuracy": float(dir_acc_oos),
        "oos_baseline_accuracy": float(max(np.mean(dir_all[oos_mask]), 1 - np.mean(dir_all[oos_mask]))),
        "feature_weights": {f: float(w) for f, w in zip(["intercept"] + DIRECTION_FEATURES, w_dir)},
    }
    
    # === Stage 2: Magnitude Model ===
    X_mag_train = X_mag[train_mask]
    y_mag_train = mag_all[train_mask]
    
    beta_mag, b0_mag, mu_mag, sd_mag, n_mag = fit_ridge(X_mag_train, y_mag_train)
    mag_pred = ridge_predict(X_mag, beta_mag, b0_mag, mu_mag, sd_mag)
    
    # Magnitude model quality
    mag_pred_oos = mag_pred[oos_mask]
    mag_actual_oos = mag_all[oos_mask]
    mag_corr_oos = float(np.corrcoef(mag_pred_oos, mag_actual_oos)[0, 1]) if len(mag_pred_oos) > 1 else 0.0
    
    results["stage2_magnitude"] = {
        "oos_correlation": mag_corr_oos,
        "mean_predicted_mag": float(np.mean(mag_pred_oos)),
        "mean_actual_mag": float(np.mean(mag_actual_oos)),
        "feature_weights": {f: float(w) for f, w in zip(["intercept"] + MAGNITUDE_FEATURES, [b0_mag] + beta_mag.tolist())},
    }
    
    # === Stage 3: Selective Trading Gate ===
    # Expected net edge = P(correct) * E[|r|] - cost
    expected_move = p_correct_dir * mag_pred
    expected_net = expected_move - TOTAL_COST_BPS
    
    # Gate conditions
    gate_confidence = p_correct_dir > MIN_DIRECTION_CONFIDENCE
    gate_magnitude = mag_pred > MIN_MAGNITUDE_BPS
    gate_spread = df["spread_bps"].to_numpy(float) < MAX_SPREAD_BPS
    gate_net_positive = expected_net > 0
    
    # Combined gate
    trade_mask = gate_confidence & gate_magnitude & gate_spread & gate_net_positive
    
    # OOS trade analysis
    oos_trade = trade_mask & oos_mask
    n_oos_trade = int(oos_trade.sum())
    n_oos = int(oos_mask.sum())
    pct_traded = n_oos_trade / n_oos * 100 if n_oos > 0 else 0
    
    if n_oos_trade > 0:
        traded_gross = float(np.mean(y_all[oos_trade]))
        traded_net = float(np.mean(y_all[oos_trade]) - TOTAL_COST_BPS)
        traded_gross_mean, traded_gross_ci_low, traded_gross_ci_high = bootstrap_ci(y_all[oos_trade])
        traded_net_mean, traded_net_ci_low, traded_net_ci_high = bootstrap_ci(y_all[oos_trade] - TOTAL_COST_BPS)
    else:
        traded_gross = 0.0
        traded_net = 0.0
        traded_gross_ci_low = 0.0
        traded_gross_ci_high = 0.0
        traded_net_ci_low = 0.0
        traded_net_ci_high = 0.0
    
    # All events net (including no-trade = 0)
    all_net = np.where(trade_mask, expected_net, 0.0)
    all_net_oos = float(np.mean(all_net[oos_mask]))
    
    results["stage3_decision"] = {
        "oos_traded_count": n_oos_trade,
        "oos_total": n_oos,
        "oos_pct_traded": float(pct_traded),
        "traded_gross_bps": float(traded_gross),
        "traded_net_bps": float(traded_net),
        "traded_gross_ci95": [float(traded_gross_ci_low), float(traded_gross_ci_high)],
        "traded_net_ci95": [float(traded_net_ci_low), float(traded_net_ci_high)],
        "all_events_net_bps": float(all_net_oos),
    }
    
    # === Verdict ===
    if pct_traded < MIN_TRADE_PCT:
        verdict = "HYPOTHESIS_REJECTED"
        reason = f"Trade frequency {pct_traded:.2f}% < {MIN_TRADE_PCT}% minimum"
    elif traded_net <= 0:
        verdict = "HYPOTHESIS_REJECTED"
        reason = f"Traded net {traded_net:.4f} bps <= 0"
    elif traded_net_ci_low <= 0:
        verdict = "INCONCLUSIVE"
        reason = f"Net CI includes 0: [{traded_net_ci_low:.4f}, {traded_net_ci_high:.4f}]"
    else:
        verdict = "POSITIVE_EDGE"
        reason = f"Traded net {traded_net:.4f} bps > 0, {pct_traded:.1f}% traded"
    
    results["verdict"] = verdict
    results["verdict_reason"] = reason
    
    # Save
    (out_dir / "v8_validation.json").write_text(json.dumps(results, indent=2, default=str))
    
    return results


def print_v8_report(results: Dict):
    """Print V8 validation report."""
    print("=" * 70)
    print("V8 VALIDATION REPORT — Direction-Magnitude Decomposition")
    print("=" * 70)
    print(f"Experiment: {results['experiment_id']}")
    print(f"Horizon: {results['horizon_ms']} ms")
    print(f"Events: {results['n_events']} (train={results['n_train']}, val={results['n_val']}, oos={results['n_oos']})")
    print(f"Cost: {results['cost_bps']} bps")
    
    print(f"\n--- Stage 1: Direction ---")
    s1 = results["stage1_direction"]
    print(f"  OOS accuracy: {s1['oos_accuracy']:.4f} (baseline: {s1['oos_baseline_accuracy']:.4f})")
    
    print(f"\n--- Stage 2: Magnitude ---")
    s2 = results["stage2_magnitude"]
    print(f"  OOS correlation: {s2['oos_correlation']:.4f}")
    print(f"  Mean predicted |r|: {s2['mean_predicted_mag']:.4f} bps")
    print(f"  Mean actual |r|: {s2['mean_actual_mag']:.4f} bps")
    
    print(f"\n--- Stage 3: Selective Trading ---")
    s3 = results["stage3_decision"]
    print(f"  OOS traded: {s3['oos_traded_count']}/{s3['oos_total']} ({s3['oos_pct_traded']:.2f}%)")
    print(f"  Traded gross: {s3['traded_gross_bps']:+.4f} bps")
    print(f"  Traded net: {s3['traded_net_bps']:+.4f} bps")
    print(f"  Traded net CI95: [{s3['traded_net_ci95'][0]:+.4f}, {s3['traded_net_ci95'][1]:+.4f}]")
    print(f"  All events net: {s3['all_events_net_bps']:+.4f} bps")
    
    print(f"\n--- VERDICT ---")
    print(f"  {results['verdict']}: {results['verdict_reason']}")
    print("=" * 70)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", type=Path, default=Path("data/research/v7_true_features.parquet"))
    ap.add_argument("--out", type=Path, default=Path("data/research/v8"))
    ap.add_argument("--horizon", type=int, default=PRIMARY_HORIZON)
    a = ap.parse_args()
    
    results = run_v8_validation(a.features, a.out, a.horizon)
    print_v8_report(results)
