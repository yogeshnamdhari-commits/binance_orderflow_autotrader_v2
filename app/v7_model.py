"""V7 model — staged architecture with full economic validation.

Pre-registered staged model hierarchy:
  Model 0: Naive baseline (predict mean return)
  Model 1: Logistic regression (directional: up/down)
  Model 2: Ridge regression (expected return, V7 features)
  Model 3: Gradient boosting (ONLY if Model 2 shows OOS edge)

Includes:
  - Binned probability calibration
  - Economic decision engine with toxicity/liquidity gates
  - Bootstrap CI, HAC-robust inference
  - Ablation study
  - Full OOS validation

Research basis:
  - Cont, Kukanov & Stoikov (2014): OFI and price impact
  - Xu, Gould & Howison (2017): Multi-level OFI
  - Gould & Bonart (2016): Queue imbalance as price predictor
  - Kolm, Turiel & Westray (2021): Deep order flow imbalance
  - Bailey & Lopez de Prado (2014): Deflated Sharpe Ratio
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional

from .v3_labels import add_labels
from .v3_model import chrono_split_masks, SPLIT_FRACTIONS
from .v7_features import V7_NEW_FEATURES, add_v7_features, V7_MULTI_LEVEL_OFI, V7_QUEUE_IMBALANCE, V7_MICROPRICE, V7_TOXICITY, V7_LIQUIDITY, V7_VOLATILITY, V7_INTERACTIONS

# V7 combined features: V5 base + V7 new
V5_FEATURES = ["ofi_l1", "ofi_norm_l1", "qi_l1", "di_l5", "di_l10",
               "mpd_bps", "spread_bps", "bid_cancel_bps", "ask_add_bps",
               "cancel_pressure", "tfi_500", "liq_depletion",
               "log_depth1", "log_depth5", "log_event_rate",
               "depth_slope_bps", "vol_500"]

V7_FEATURES = V5_FEATURES + V7_NEW_FEATURES

PRIMARY_HORIZON = 500
RIDGE_ALPHA = 0.05
MAKER_FEE_BPS = 2.0
TAKER_GATE_BPS = 4.67
SAFETY_MARGIN_BPS = 0.5


def prepare_v7_data(feature_path: str | Path,
                    horizon_ms: int = PRIMARY_HORIZON) -> Tuple[pd.DataFrame, np.ndarray, np.ndarray, np.ndarray]:
    """Load V7 features, add labels, return dataframe with splits."""
    df = pd.read_parquet(feature_path)
    
    # Add labels
    df = add_labels(df, horizons=(horizon_ms,))
    
    # Filter valid rows
    label_col = f"r_{horizon_ms}"
    required = V7_FEATURES + [label_col, "mid", "spread_bps", "regime"]
    mask = (
        df["mid"].notna() & (df["mid"] > 0) &
        df["spread_bps"].notna() & (df["spread_bps"] > 0) &
        df[required].notna().all(axis=1)
    )
    df = df.loc[mask].reset_index(drop=True)
    
    # Chronological splits
    splits = chrono_split_masks(df)
    train_mask = splits[0]["mask"]
    val_mask = splits[1]["mask"]
    oos_mask = splits[2]["mask"]
    
    return df, train_mask, val_mask, oos_mask


def fit_ridge(Xtr: np.ndarray, ytr: np.ndarray, alpha: float = RIDGE_ALPHA):
    """Closed-form ridge regression."""
    mus = np.nanmean(Xtr, axis=0)
    sds = np.nanstd(Xtr, axis=0)
    sds = np.where(sds < 1e-12, 1.0, sds)
    Z = (Xtr - mus) / sds
    ok = np.isfinite(Z).all(axis=1) & np.isfinite(ytr)
    if ok.sum() < 200:
        raise ValueError(f"insufficient train rows: {ok.sum()}")
    A = Z[ok].T @ Z[ok] + alpha * np.eye(Z.shape[1])
    b = Z[ok].T @ ytr[ok]
    beta = np.linalg.solve(A, b)
    b0 = float(ytr[ok].mean() - beta @ np.nanmean(Z[ok], axis=0))
    pred = b0 + Z[ok] @ beta
    resid = ytr[ok] - pred
    sst = np.sum((ytr[ok] - ytr[ok].mean()) ** 2)
    r2 = 1.0 - np.sum(resid ** 2) / sst if sst > 0 else 0.0
    return beta, b0, mus, sds, float(r2), int(ok.sum())


def ridge_predict(X: np.ndarray, beta: np.ndarray, b0: float,
                  mus: np.ndarray, sds: np.ndarray) -> np.ndarray:
    """Predict using ridge coefficients."""
    Z = (X - mus) / sds
    Z = np.where(np.isfinite(Z), Z, 0.0)
    return b0 + Z @ beta


def fit_binned_calibration(pred_raw: np.ndarray, y_true: np.ndarray,
                           n_bins: int = 15) -> Dict:
    """Fit binned calibration map."""
    finite = np.isfinite(pred_raw) & np.isfinite(y_true)
    pred_raw = pred_raw[finite]
    y_true = y_true[finite]
    
    if len(pred_raw) == 0:
        return {"bin_edges": np.array([]), "bin_means": np.array([]),
                "bin_counts": np.array([]), "bin_stderr": np.array([]),
                "n_bins": n_bins, "min_pred": 0, "max_pred": 0}
    
    min_pred = float(np.min(pred_raw))
    max_pred = float(np.max(pred_raw))
    if min_pred == max_pred:
        min_pred -= 1e-6
        max_pred += 1e-6
    
    bin_width = (max_pred - min_pred) / n_bins
    bin_edges = np.linspace(min_pred, max_pred, n_bins + 1)
    bin_indices = np.clip(
        np.floor((pred_raw - min_pred) / bin_width).astype(int), 0, n_bins - 1
    )
    
    bin_means = np.zeros(n_bins)
    bin_counts = np.zeros(n_bins, dtype=int)
    bin_stderr = np.zeros(n_bins)
    
    for idx in range(n_bins):
        mask = bin_indices == idx
        n = mask.sum()
        bin_counts[idx] = n
        if n > 0:
            bin_means[idx] = np.mean(y_true[mask])
            bin_stderr[idx] = np.std(y_true[mask]) / np.sqrt(n)
    
    return {
        "bin_edges": bin_edges, "bin_means": bin_means,
        "bin_counts": bin_counts, "bin_stderr": bin_stderr,
        "n_bins": n_bins, "min_pred": min_pred, "max_pred": max_pred
    }


def apply_calibration(pred_raw: np.ndarray, calib: Dict) -> np.ndarray:
    """Apply binned calibration to raw predictions."""
    calibrated = np.full(len(pred_raw), np.nan, dtype=float)
    finite = np.isfinite(pred_raw)
    if not np.any(finite):
        return calibrated
    
    pred = np.clip(pred_raw[finite], calib["min_pred"], calib["max_pred"])
    n_bins = calib["n_bins"]
    bin_width = (calib["max_pred"] - calib["min_pred"]) / n_bins
    
    if bin_width == 0:
        bin_indices = np.zeros(len(pred), dtype=int)
    else:
        bin_indices = np.clip(
            np.floor((pred - calib["min_pred"]) / bin_width).astype(int), 0, n_bins - 1
        )
    
    calibrated[finite] = calib["bin_means"][bin_indices]
    return calibrated


def bootstrap_ci(values: np.ndarray, n_boot: int = 2000, alpha: float = 0.05) -> Tuple[float, float, float]:
    """Compute bootstrap confidence interval for mean."""
    values = values[np.isfinite(values)]
    if len(values) < 10:
        return float(np.nanmean(values)), float('nan'), float('nan')
    
    rng = np.random.RandomState(42)
    boot_means = np.array([
        np.mean(rng.choice(values, size=len(values), replace=True))
        for _ in range(n_boot)
    ])
    point = float(np.mean(values))
    lower = float(np.percentile(boot_means, 100 * alpha / 2))
    upper = float(np.percentile(boot_means, 100 * (1 - alpha / 2)))
    return point, lower, upper


def hac_se(values: np.ndarray, max_lag: int = 10) -> float:
    """HAC-robust standard error (Newey-West)."""
    values = values[np.isfinite(values)]
    if len(values) < 2:
        return 0.0
    demeaned = values - np.mean(values)
    n = len(demeaned)
    gamma0 = np.sum(demeaned ** 2) / n
    var = gamma0
    for lag in range(1, min(max_lag + 1, n)):
        w = 1.0 - lag / (max_lag + 1)  # Bartlett kernel
        gamma_l = np.sum(demeaned[lag:] * demeaned[:n-lag]) / n
        var += 2 * w * gamma_l
    return np.sqrt(max(var, 0) / n)


def economic_gate(gross_bps: float, toxicity_state: str = "LOW_TOXICITY",
                  liquidity_state: str = "NORMAL", spread_bps: float = 0.0,
                  vpin: float = 0.0) -> Tuple[bool, str, Dict]:
    """Economic decision gate: expected net edge > 0 after all costs.
    
    Returns: (pass, reason, gate_details)
    """
    gates = {}
    
    # Gate 1: Liquidity regime
    gates["liquidity"] = liquidity_state == "NORMAL"
    if not gates["liquidity"]:
        return False, f"liquidity={liquidity_state}", gates
    
    # Gate 2: Toxicity
    gates["toxicity"] = toxicity_state != "HIGH_TOXICITY"
    if not gates["toxicity"]:
        return False, f"toxicity={toxicity_state}", gates
    
    # Gate 3: Spread cost
    gates["spread_ok"] = spread_bps < 3.0
    if not gates["spread_ok"]:
        return False, f"spread={spread_bps:.3f}bps >= 3.0", gates
    
    # Gate 4: Gross > 0
    gates["gross_positive"] = gross_bps > 0
    if not gates["gross_positive"]:
        return False, f"gross={gross_bps:.4f}bps <= 0", gates
    
    # Gate 5: Net after maker fee + safety margin
    cost = MAKER_FEE_BPS + SAFETY_MARGIN_BPS
    net = gross_bps - cost
    gates["net_positive"] = net > 0
    gates["net_bps"] = net
    gates["cost_bps"] = cost
    
    if not gates["net_positive"]:
        return False, f"net={net:.4f}bps <= 0 (gross={gross_bps:.4f}, cost={cost})", gates
    
    return True, "ALL_GATES_PASS", gates


def validate_model(y_true: np.ndarray, y_pred: np.ndarray, oos_mask: np.ndarray,
                   gate_bps: float = MAKER_FEE_BPS) -> Dict:
    """Full OOS validation with economic and statistical gates."""
    y_oos = y_true[oos_mask]
    pred_oos = y_pred[oos_mask]
    
    # Filter finite
    finite = np.isfinite(y_oos) & np.isfinite(pred_oos)
    y_oos = y_oos[finite]
    pred_oos = pred_oos[finite]
    
    n = len(y_oos)
    if n < 10:
        return {"n": n, "verdict": "INSUFFICIENT_DATA"}
    
    # Directional accuracy
    dir_correct = np.sum(np.sign(pred_oos) == np.sign(y_oos))
    dir_accuracy = dir_correct / n
    
    # Gross expectancy (using calibrated predictions)
    gross = pred_oos  # Already calibrated
    gross_mean, gross_ci_low, gross_ci_high = bootstrap_ci(gross)
    gross_se = hac_se(gross)
    gross_z = gross_mean / gross_se if gross_se > 0 else 0.0
    gross_p = 2 * (1 - _norm_cdf(abs(gross_z)))
    
    # Net expectancy
    net = gross - gate_bps
    net_mean, net_ci_low, net_ci_high = bootstrap_ci(net)
    net_se = hac_se(net)
    net_z = net_mean / net_se if net_se > 0 else 0.0
    net_p = 2 * (1 - _norm_cdf(abs(net_z)))
    
    # % above gate
    pct_above_gate = np.sum(gross > gate_bps) / n * 100
    
    # Per-direction
    long_mask = pred_oos > 0
    short_mask = pred_oos < 0
    long_gross = np.mean(y_oos[long_mask]) if long_mask.sum() > 0 else float('nan')
    short_gross = np.mean(y_oos[short_mask]) if short_mask.sum() > 0 else float('nan')
    long_net = long_gross - gate_bps if np.isfinite(long_gross) else float('nan')
    short_net = short_gross - gate_bps if np.isfinite(short_gross) else float('nan')
    
    # Verdict
    verdict = _determine_verdict(net_mean, net_ci_low, net_ci_high, pct_above_gate, n)
    
    return {
        "n": int(n),
        "directional_accuracy": float(dir_accuracy),
        "gross_mean_bps": float(gross_mean),
        "gross_ci95_low": float(gross_ci_low),
        "gross_ci95_high": float(gross_ci_high),
        "gross_hac_se": float(gross_se),
        "gross_hac_z": float(gross_z),
        "gross_hac_p": float(gross_p),
        "net_mean_bps": float(net_mean),
        "net_ci95_low": float(net_ci_low),
        "net_ci95_high": float(net_ci_high),
        "net_hac_se": float(net_se),
        "net_hac_z": float(net_z),
        "net_hac_p": float(net_p),
        "gate_bps": float(gate_bps),
        "pct_above_gate": float(pct_above_gate),
        "long": {
            "n": int(long_mask.sum()),
            "gross_bps": float(long_gross),
            "net_bps": float(long_net),
        },
        "short": {
            "n": int(short_mask.sum()),
            "gross_bps": float(short_gross),
            "net_bps": float(short_net),
        },
        "verdict": verdict,
    }


def _norm_cdf(x):
    """Standard normal CDF."""
    from scipy import special
    return 0.5 * (1 + special.erf(x / np.sqrt(2)))


def _determine_verdict(net_mean, net_ci_low, net_ci_high, pct_above_gate, n):
    """Determine validation verdict."""
    if net_mean <= 0:
        return "NEGATIVE_EDGE"
    if net_ci_low <= 0:
        return "INCONCLUSIVE"
    if pct_above_gate < 5.0:
        return "LOW_SIGNAL_FREQUENCY"
    if n < 100:
        return "INSUFFICIENT_SAMPLE"
    return "POSITIVE_EDGE"


def train_and_validate_v7(feature_path: str | Path,
                          out_dir: str | Path,
                          horizon_ms: int = PRIMARY_HORIZON) -> Dict:
    """Full V7 training and validation pipeline.
    
    Trains staged models and validates with economic gates.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Prepare data
    df, train_mask, val_mask, oos_mask = prepare_v7_data(feature_path, horizon_ms)
    label_col = f"r_{horizon_ms}"
    
    results = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "horizon_ms": horizon_ms,
        "feature_set": "V7",
        "n_features": len(V7_FEATURES),
        "features": V7_FEATURES,
        "n_train": int(train_mask.sum()),
        "n_validation": int(val_mask.sum()),
        "n_oos": int(oos_mask.sum()),
    }
    
    # Model 0: Naive baseline
    y_train = df.loc[train_mask, label_col].to_numpy(float)
    y_oos = df.loc[oos_mask, label_col].to_numpy(float)
    naive_pred = np.full(oos_mask.sum(), np.mean(y_train[np.isfinite(y_train)]))
    results["model_0_naive"] = validate_model(
        df[label_col].to_numpy(float), 
        np.full(len(df), naive_pred[0]),
        oos_mask
    )
    
    # Model 2: Ridge with V7 features
    X_all = df[V7_FEATURES].to_numpy(float)
    y_all = df[label_col].to_numpy(float)
    
    X_train = X_all[train_mask]
    y_train = y_all[train_mask]
    X_val = X_all[val_mask]
    y_val = y_all[val_mask]
    X_oos = X_all[oos_mask]
    y_oos = y_all[oos_mask]
    
    # Fit ridge
    beta, b0, mu, sd, r2_train, n_train = fit_ridge(X_train, y_train, alpha=RIDGE_ALPHA)
    
    # Calibrate on validation set
    val_pred_raw = ridge_predict(X_val, beta, b0, mu, sd)
    calib = fit_binned_calibration(val_pred_raw, y_val)
    
    # OOS predictions
    oos_pred_raw = ridge_predict(X_oos, beta, b0, mu, sd)
    oos_pred_cal = apply_calibration(oos_pred_raw, calib)
    
    # Full dataframe predictions (for validation function)
    all_pred_raw = ridge_predict(X_all, beta, b0, mu, sd)
    all_pred_cal = apply_calibration(all_pred_raw, calib)
    
    results["model_2_ridge_v7"] = validate_model(y_all, all_pred_cal, oos_mask)
    results["model_2_ridge_v7"]["r2_train"] = float(r2_train)
    results["model_2_ridge_v7"]["n_train"] = int(n_train)
    
    # Save model
    model_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_type": "V7_Ridge",
        "alpha": RIDGE_ALPHA,
        "features": V7_FEATURES,
        "horizon_ms": horizon_ms,
        "coef": [float(x) for x in beta],
        "intercept": float(b0),
        "mean": [float(x) for x in mu],
        "std": [float(x) for x in sd],
        "r2_train": float(r2_train),
        "n_train": int(n_train),
        "calibration": {
            "bin_edges": calib["bin_edges"].tolist(),
            "bin_means": calib["bin_means"].tolist(),
            "bin_counts": calib["bin_counts"].tolist(),
            "n_bins": calib["n_bins"],
            "min_pred": calib["min_pred"],
            "max_pred": calib["max_pred"],
        }
    }
    (out_dir / "v7_model.json").write_text(json.dumps(model_data, indent=1))
    
    # Save results
    (out_dir / "v7_validation.json").write_text(json.dumps(results, indent=1, default=str))
    
    return results


def run_ablation(feature_path: str | Path,
                 out_dir: str | Path,
                 horizon_ms: int = PRIMARY_HORIZON) -> Dict:
    """Run ablation study: test feature subsets."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    df, train_mask, val_mask, oos_mask = prepare_v7_data(feature_path, horizon_ms)
    label_col = f"r_{horizon_ms}"
    y_all = df[label_col].to_numpy(float)
    
    # Feature subsets to test
    subsets = {
        "V5_baseline": V5_FEATURES,
        "V5_plus_multi_level_ofi": V5_FEATURES + V7_MULTI_LEVEL_OFI,
        "V5_plus_queue": V5_FEATURES + V7_QUEUE_IMBALANCE,
        "V5_plus_microprice": V5_FEATURES + V7_MICROPRICE,
        "V5_plus_toxicity": V5_FEATURES + V7_TOXICITY,
        "V5_plus_liquidity": V5_FEATURES + V7_LIQUIDITY,
        "V5_plus_volatility": V5_FEATURES + V7_VOLATILITY,
        "V5_plus_interactions": V5_FEATURES + V7_INTERACTIONS,
        "V7_full": V7_FEATURES,
    }
    
    ablation_results = {}
    
    for name, features in subsets.items():
        # Check all features exist
        missing = [f for f in features if f not in df.columns]
        if missing:
            ablation_results[name] = {"error": f"missing features: {missing}"}
            continue
        
        X_all = df[features].to_numpy(float)
        X_train = X_all[train_mask]
        y_train = y_all[train_mask]
        X_val = X_all[val_mask]
        y_val = y_all[val_mask]
        
        try:
            beta, b0, mu, sd, r2_train, n_train = fit_ridge(X_train, y_train, alpha=RIDGE_ALPHA)
            
            val_pred = ridge_predict(X_val, beta, b0, mu, sd)
            calib = fit_binned_calibration(val_pred, y_val)
            
            all_pred = ridge_predict(X_all, beta, b0, mu, sd)
            all_pred_cal = apply_calibration(all_pred, calib)
            
            val_result = validate_model(y_all, all_pred_cal, oos_mask)
            val_result["r2_train"] = float(r2_train)
            val_result["n_features"] = len(features)
            ablation_results[name] = val_result
        except Exception as e:
            ablation_results[name] = {"error": str(e)}
    
    # Save ablation results
    ablation_path = out_dir / "v7_ablation.json"
    ablation_path.write_text(json.dumps(ablation_results, indent=1, default=str))
    
    return ablation_results


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", type=Path,
                    default=Path("data/research/v7_features.parquet"))
    ap.add_argument("--out", type=Path,
                    default=Path("data/research/v7"))
    ap.add_argument("--ablation", action="store_true")
    a = ap.parse_args()
    
    print("Training V7 model...")
    results = train_and_validate_v7(a.features, a.out)
    
    print("\n=== V7 Validation Results ===")
    for model_name, model_res in results.items():
        if isinstance(model_res, dict) and "verdict" in model_res:
            print(f"\n{model_name}:")
            print(f"  Verdict: {model_res['verdict']}")
            print(f"  OOS samples: {model_res['n']}")
            print(f"  Gross: {model_res['gross_mean_bps']:.4f} bps "
                  f"[{model_res['gross_ci95_low']:.4f}, {model_res['gross_ci95_high']:.4f}]")
            print(f"  Net: {model_res['net_mean_bps']:.4f} bps "
                  f"[{model_res['net_ci95_low']:.4f}, {model_res['net_ci95_high']:.4f}]")
            print(f"  % above gate: {model_res['pct_above_gate']:.2f}%")
            print(f"  HAC p-value: {model_res['net_hac_p']:.6f}")
    
    if a.ablation:
        print("\n=== Ablation Study ===")
        ablation = run_ablation(a.features, a.out)
        for name, res in ablation.items():
            if "error" in res:
                print(f"  {name}: ERROR - {res['error']}")
            else:
                print(f"  {name:30s}: net={res['net_mean_bps']:.4f} bps, "
                      f"verdict={res['verdict']}, n_feats={res['n_features']}")
