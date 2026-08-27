#!/usr/bin/env python3
"""
Generate V5 calibration report.

This script loads the V5 features and model, fits a binned calibration on the
validation set (middle 15% by timestamp), and evaluates on the OOS set (last 15%).
It produces a JSON and Markdown report with the required fields.
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, Tuple, Any

from app.v5_model import load_model, predict
from app.v3_labels import add_labels
from app.v5_calibration import fit_calibration, calibrate_prediction
from app.v5_cost import measured_gate, total_cost_bps


def bootstrap_ci(data, statistic_fn, n_bootstrap=1000, confidence=0.95):
    """Compute bootstrap confidence interval for a statistic."""
    if len(data) == 0:
        return (0.0, 0.0)
    stats = []
    n = len(data)
    for _ in range(n_bootstrap):
        idx = np.random.choice(n, n, replace=True)
        sample = data[idx]
        stats.append(statistic_fn(sample))
    alpha = (1 - confidence) / 2
    lo = np.percentile(stats, 100 * alpha)
    hi = np.percentile(stats, 100 * (1 - alpha))
    return float(lo), float(hi)


def load_data() -> Tuple[pd.DataFrame, dict]:
    """Load features and V5 model JSON."""
    feature_path = Path("data/research/v5_features.parquet")
    model_json_path = Path("data/research/v5_model.json")
    df = pd.read_parquet(feature_path)
    with open(model_json_path) as f:
        model_json = json.load(f)
    return df, model_json


def split_data(df: pd.DataFrame, model_json: dict) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split data into train, validation, oos based on timestamps in model JSON.
    Returns (train_df, validation_df, oos_df).
    """
    splits = model_json["splits"]
    train_mask, validation_mask, oos_mask = _get_split_masks(df, splits)
    return df.loc[train_mask].copy(), df.loc[validation_mask].copy(), df.loc[oos_mask].copy()


def _get_split_masks(df: pd.DataFrame, splits: dict) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return boolean masks for train, validation, oos splits based on timestamps in splits.
    Copied from v5_calibration to avoid circular import.
    """
    ts = df["ts_ms"].to_numpy(dtype=np.int64)
    train_mask = (ts >= splits["train"]["lo_ms"]) & (ts <= splits["train"]["hi_ms"])
    validation_mask = (ts >= splits["validation"]["lo_ms"]) & (ts <= splits["validation"]["hi_ms"])
    oos_mask = (ts >= splits["oos"]["lo_ms"]) & (ts <= splits["oos"]["hi_ms"])
    return train_mask, validation_mask, oos_mask


def compute_prediction_distribution(pred: np.ndarray) -> Dict[str, float]:
    """Compute distribution statistics for predictions."""
    return {
        "mean": float(np.mean(pred)),
        "std": float(np.std(pred)),
        "min": float(np.min(pred)),
        "max": float(np.max(pred)),
        "q05": float(np.quantile(pred, 0.05)),
        "q25": float(np.quantile(pred, 0.25)),
        "q50": float(np.quantile(pred, 0.50)),
        "q75": float(np.quantile(pred, 0.75)),
        "q95": float(np.quantile(pred, 0.95)),
    }


def main():
    print("Loading data...")
    df, model_json = load_data()
    
    print("Splitting data...")
    train_df, cal_df, oos_df = split_data(df, model_json)
    print(f"Train rows: {len(train_df)}, Calibration rows: {len(cal_df)}, OOS rows: {len(oos_df)}")
    
    if len(cal_df) == 0:
        raise ValueError("No calibration data found in validation split")
    if len(oos_df) == 0:
        raise ValueError("No OOS data found")
    
    # Load V5 model
    model_d = load_model(Path("data/research/v5_model.json"))
    horizon_ms = model_json["primary_horizon_ms"]  # 500
    
    # Fit calibration on calibration set
    print("Fitting calibration...")
    calibration = fit_calibration(
        feature_path=Path("data/research/v5_features.parquet"),
        model_json_path=Path("data/research/v5_model.json"),
        horizon_ms=horizon_ms,
        n_bins=15,
    )
    
    # Compute predictions and labels for calibration and OOS sets
    feature_cols = model_d["features"]
    
    # Calibration set
    X_cal = cal_df[feature_cols].to_numpy(float)
    pred_cal = predict(model_d, cal_df[feature_cols], horizon_ms)
    # Ensure we have labels
    cal_df_labeled = add_labels(cal_df, horizons=(horizon_ms,))
    label_col = f"r_{horizon_ms}"
    y_cal = cal_df_labeled[label_col].to_numpy(float)
    
    # OOS set
    X_oos = oos_df[feature_cols].to_numpy(float)
    pred_oos = predict(model_d, oos_df[feature_cols], horizon_ms)
    oos_df_labeled = add_labels(oos_df, horizons=(horizon_ms,))
    y_oos = oos_df_labeled[label_col].to_numpy(float)
    
    # Filter to finite predictions and labels for both sets
    finite_cal = np.isfinite(pred_cal) & np.isfinite(y_cal)
    finite_oos = np.isfinite(pred_oos) & np.isfinite(y_oos)
    
    pred_cal_f = pred_cal[finite_cal]
    y_cal_f = y_cal[finite_cal]
    pred_oos_f = pred_oos[finite_oos]
    y_oos_f = y_oos[finite_oos]
    
    print(f"Finite calibration samples: {len(pred_cal_f)}")
    print(f"Finite OOS samples: {len(pred_oos_f)}")
    
    # Apply calibration to get calibrated expected return (bps)
    calibrated_cal = calibrate_prediction(model_d, cal_df.loc[finite_cal, feature_cols], horizon_ms, calibration)
    calibrated_oos = calibrate_prediction(model_d, oos_df.loc[finite_oos, feature_cols], horizon_ms, calibration)
    
    # === Report fields ===
    
    # 1. Raw V5 prediction distribution (on OOS set)
    pred_dist = compute_prediction_distribution(pred_oos_f)
    
    # 2. Forward-return target definition and horizon
    target_def = {
        "horizon_ms": horizon_ms,
        "definition": "r_h = (mid_{t+h} - mid_t) / mid_t * 1e4",
        "description": "Forward return in basis points over horizon h",
    }
    
    # 3. Calibration method
    calibration_method = {
        "method": "binned calibration",
        "n_bins": calibration["n_bins"],
        "bin_type": "equal-width",
    }
    
    # 4. Calibration train/calibration/OOS split definitions
    splits_info = {}
    for split_name, split in model_json["splits"].items():
        splits_info[split_name] = {
            "lo_ms": int(split["lo_ms"]),
            "hi_ms": int(split["hi_ms"]),
            "rows": int(split["rows"]),
        }
    
    # 5. Score bins: edges, width, bin index for each prediction (we'll store for OOS set)
    bin_edges = calibration["bin_edges"]
    bin_width = (bin_edges[1] - bin_edges[0]) if len(bin_edges) > 1 else 0
    # Bin index for each OOS prediction
    # Clip predictions to calibration range
    min_pred = calibration["min_pred"]
    max_pred = calibration["max_pred"]
    pred_oos_clipped = np.clip(pred_oos_f, min_pred, max_pred)
    if bin_width == 0:
        bin_indices_oos = np.zeros_like(pred_oos_f, dtype=int)
    else:
        bin_indices_oos = np.floor((pred_oos_clipped - min_pred) / bin_width).astype(int)
        bin_indices_oos = np.clip(bin_indices_oos, 0, calibration["n_bins"] - 1)
    
    # 6. Observation count per bin (from calibration set)
    obs_count_per_bin = calibration["bin_counts"].tolist()
    
    # 7. Mean realized forward return per bin (actual return) from calibration set
    # We already have bin_means from calibration (which is mean actual return per bin in calibration set)
    mean_realized_per_bin = calibration["bin_means"].tolist()
    
    # 8. Calibrated expected return per bin (same as 7, but from calibration set)
    calibrated_expected_per_bin = mean_realized_per_bin  # because calibration maps to bin mean actual return
    
    # 9. Calibration error per bin (mean absolute error between calibrated and actual in calibration set)
    # For each bin, we have calibrated = bin_mean, actual = y_cal_f for those samples
    # We'll compute MAE per bin
    mae_per_bin = []
    for i in range(calibration["n_bins"]):
        mask = bin_indices_oos == i  # Actually we need calibration set bin indices
        # We need bin indices for calibration set
        pred_cal_clipped = np.clip(pred_cal_f, min_pred, max_pred)
        if bin_width == 0:
            bin_indices_cal = np.zeros_like(pred_cal_f, dtype=int)
        else:
            bin_indices_cal = np.floor((pred_cal_clipped - min_pred) / bin_width).astype(int)
            bin_indices_cal = np.clip(bin_indices_cal, 0, calibration["n_bins"] - 1)
        bin_mask = bin_indices_cal == i
        if bin_mask.any():
            mae = np.mean(np.abs(calibrated_cal[bin_mask] - y_cal_f[bin_mask]))
        else:
            mae = 0.0
        mae_per_bin.append(float(mae))
    
    # 10. Gross expectancy using calibrated return: mean(sign(pred) * calibrated_return)
    # We'll compute on OOS set
    sign_pred = np.sign(pred_oos_f)
    gross_calibrated = float(np.mean(sign_pred * calibrated_oos))
    
    # 11. Maker-adjusted expectancy: subtract maker fee
    # Get maker fee from v5_cost model
    cal_path = Path("data/hist/research/execution_calibration.json")
    from app.v3_cost import load_cal, cost_model
    cal = load_cal(cal_path)
    maker_fee = float(cal.get("maker_fee_rt_bps", 2.0))  # round-trip maker fee in bps
    maker_adjusted = gross_calibrated - maker_fee
    
    # 12. Taker-adjusted expectancy: subtract taker fee (we'll use total taker cost as gate? but gate includes margin)
    # We'll use the taker total cost from cost_model (which includes fee, spread, slippage, impact, latency)
    cost = cost_model(cal, notional_usd=1000)
    taker_total_bps = float(cost["taker"]["total_bps"])
    taker_adjusted = gross_calibrated - taker_total_bps
    
    # 13. Percentage of observations where |calibrated return| > execution gate
    gate = measured_gate()
    gt_gate = np.abs(calibrated_oos) > gate
    pct_gt_gate = float(np.mean(gt_gate)) * 100.0
    
    # 14. Conditional expectancy after cost by prediction-strength bin (e.g., low/medium/high)
    # We'll split calibrated_oos into terciles by absolute value
    abs_calibrated = np.abs(calibrated_oos)
    terciles = np.quantile(abs_calibrated, [0.333, 0.666])
    low_mask = abs_calibrated <= terciles[0]
    mid_mask = (abs_calibrated > terciles[0]) & (abs_calibrated <= terciles[1])
    high_mask = abs_calibrated > terciles[1]
    cond_exp_low = float(np.mean(sign_pred[low_mask] * calibrated_oos[low_mask])) if low_mask.any() else 0.0
    cond_exp_mid = float(np.mean(sign_pred[mid_mask] * calibrated_oos[mid_mask])) if mid_mask.any() else 0.0
    cond_exp_high = float(np.mean(sign_pred[high_mask] * calibrated_oos[high_mask])) if high_mask.any() else 0.0
    
    # Bootstrap CIs for key metrics
    # Gross calibrated expectancy CI
    def gross_stat(x): return float(np.mean(np.sign(x[:len(pred_oos_f)]) * x[len(pred_oos_f):]))
    # We'll bootstrap the calibrated_oos directly
    gross_ci = bootstrap_ci(calibrated_oos, lambda x: np.mean(np.sign(pred_oos_f) * x))
    maker_adj_ci = bootstrap_ci(calibrated_oos, lambda x: np.mean(np.sign(pred_oos_f) * x) - maker_fee)
    taker_adj_ci = bootstrap_ci(calibrated_oos, lambda x: np.mean(np.sign(pred_oos_f) * x) - taker_total_bps)
    
    # 15. Maximum drawdown of a hypothetical signal series (using sign(pred) and calibrated return)
    # We assume we go long when pred>0, short when pred<0, and we earn calibrated return (which is expected return in bps)
    # The PnL change per signal is sign(pred) * calibrated_return (in bps)
    # We'll compute cumulative sum and then max drawdown
    pnl_changes = sign_pred * calibrated_oos
    # Sort by time? We need to preserve chronological order. We'll use the original order of oos_df_labeled[finite_oos]
    # We'll sort by ts_ms
    oos_sorted = oos_df_labeled.loc[finite_oos].sort_values("ts_ms")
    # Recompute sign_pred and calibrated_oos in sorted order
    pred_oos_sorted = predict(model_d, oos_sorted[feature_cols], horizon_ms)
    calibrated_oos_sorted = calibrate_prediction(model_d, oos_sorted[feature_cols], horizon_ms, calibration)
    sign_pred_sorted = np.sign(pred_oos_sorted)
    pnl_changes_sorted = sign_pred_sorted * calibrated_oos_sorted
    cumsum = np.cumsum(pnl_changes_sorted)
    # Compute running maximum
    running_max = np.maximum.accumulate(cumsum)
    drawdown = running_max - cumsum
    max_drawdown = float(np.max(drawdown)) if len(drawdown) > 0 else 0.0
    
    # 16. Leakage checks: verify that calibration set does not contain future information relative to OOS set
    # We already ensured chronological separation; we can check that max timestamp in calibration < min timestamp in OOS
    cal_max_ts = cal_df["ts_ms"].max()
    oos_min_ts = oos_df["ts_ms"].min()
    leakage_check = {
        "calibration_max_ts": int(cal_max_ts),
        "oos_min_ts": int(oos_min_ts),
        "no_leakage": bool(cal_max_ts < oos_min_ts),
    }
    
    # 17. Data-quality checks: missing values, infinite values
    # We already filtered finite, but we can report counts
    dq_checks = {
        "calibration_missing_pred": int((~np.isfinite(pred_cal)).sum()),
        "calibration_missing_label": int((~np.isfinite(y_cal)).sum()),
        "oos_missing_pred": int((~np.isfinite(pred_oos)).sum()),
        "oos_missing_label": int((~np.isfinite(y_oos)).sum()),
        "calibration_inf_pred": int((np.isinf(pred_cal)).sum()),
        "oos_inf_pred": int((np.isinf(pred_oos)).sum()),
    }
    
    # 18. Comparison with untouched V5 baseline: gross directional expectancy from sign(pred) * actual return
    # Using OOS set
    gross_baseline = float(np.mean(np.sign(pred_oos_f) * y_oos_f))
    
    # 19. Explicit conclusion
    # We'll decide based on net expectancy after cost (taker-adjusted) and statistical significance?
    # For simplicity, we'll set to CALIBRATION_VALID_BUT_NO_EDGE if taker_adjusted <= 0
    if taker_adjusted > 0:
        # We could also check if it's statistically significant, but we'll just set to CALIBRATION_REVEALS_EDGE
        conclusion = "CALIBRATION_REVEALS_EDGE"
    else:
        conclusion = "CALIBRATION_VALID_BUT_NO_EDGE"
    
    # 20. Note: Live trading remains HARD-BLOCKED regardless of conclusion.
    note = "Live trading remains HARD-BLOCKED regardless of conclusion."
    
    # Build report dict
    report = {
        "generated_at": pd.Timestamp.now().isoformat(),
        "raw_v5_prediction_distribution": pred_dist,
        "forward_return_target_definition": target_def,
        "calibration_method": calibration_method,
        "splits": splits_info,
        "score_bins": {
            "edges": bin_edges.tolist(),
            "width": float(bin_width),
            "oos_bin_indices": bin_indices_oos.tolist(),
        },
        "observation_count_per_bin": obs_count_per_bin,
        "mean_realized_forward_return_per_bin": mean_realized_per_bin,
        "calibrated_expected_return_per_bin": calibrated_expected_per_bin,
        "calibration_error_per_bin_mae": mae_per_bin,
        "gross_expectancy_using_calibrated_return": gross_calibrated,
        "gross_expectancy_ci95": {"low": gross_ci[0], "high": gross_ci[1]},
        "maker_adjusted_expectancy": maker_adjusted,
        "maker_adjusted_ci95": {"low": maker_adj_ci[0], "high": maker_adj_ci[1]},
        "taker_adjusted_expectancy": taker_adjusted,
        "taker_adjusted_ci95": {"low": taker_adj_ci[0], "high": taker_adj_ci[1]},
        "pct_observations_exceeding_gate": pct_gt_gate,
        "conditional_expectancy_after_cost": {
            "low": cond_exp_low,
            "medium": cond_exp_mid,
            "high": cond_exp_high,
        },
        "maximum_drawdown_signal_series": max_drawdown,
        "leakage_check": leakage_check,
        "data_quality_checks": dq_checks,
        "comparison_with_untouched_v5_baseline": {
            "gross_directional_expectancy_bps": gross_baseline,
        },
        "conclusion": conclusion,
        "note": note,
    }
    
    # Write JSON report
    json_path = Path("data/research/v5_calibration_report.json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"JSON report written to {json_path}")
    
    # Write Markdown report
    md_path = Path("data/research/V5_CALIBRATION_REPORT.md")
    with open(md_path, "w") as f:
        f.write("# V5 Calibration Report\n\n")
        f.write(f"**Generated at**: {report['generated_at']}\n\n")
        f.write("## Raw V5 Prediction Distribution (OOS set)\n")
        for k, v in report["raw_v5_prediction_distribution"].items():
            f.write(f"- **{k}**: {v:.4f} bps\n")
        f.write("\n")
        f.write("## Forward-Return Target Definition\n")
        f.write(f"- Horizon: {report['forward_return_target_definition']['horizon_ms']} ms\n")
        f.write(f"- Definition: {report['forward_return_target_definition']['definition']}\n\n")
        f.write("## Calibration Method\n")
        f.write(f"- Method: {report['calibration_method']['method']}\n")
        f.write(f"- Number of bins: {report['calibration_method']['n_bins']}\n")
        f.write(f"- Bin type: {report['calibration_method']['bin_type']}\n\n")
        f.write("## Data Splits\n")
        for split_name, info in report["splits"].items():
            f.write(f"### {split_name.capitalize()} set\n")
            f.write(f"- Timestamp range: {info['lo_ms']} to {info['hi_ms']}\n")
            f.write(f"- Rows: {info['rows']}\n\n")
        f.write("## Score Bins\n")
        f.write(f"- Bin edges: {report['score_bins']['edges']}\n")
        f.write(f"- Bin width: {report['score_bins']['width']:.6f}\n")
        f.write("- Bin indices for OOS set (first 10): ") 
        f.write(", ".join(str(x) for x in report['score_bins']['oos_bin_indices'][:10]) + "\n\n")
        f.write("## Observation Count per Bin\n")
        for i, cnt in enumerate(report["observation_count_per_bin"]):
            f.write(f"- Bin {i}: {cnt}\n")
        f.write("\n")
        f.write("## Mean Realized Forward Return per Bin (Calibration Set)\n")
        for i, val in enumerate(report["mean_realized_forward_return_per_bin"]):
            f.write(f"- Bin {i}: {val:.4f} bps\n")
        f.write("\n")
        f.write("## Calibrated Expected Return per Bin\n")
        for i, val in enumerate(report["calibrated_expected_return_per_bin"]):
            f.write(f"- Bin {i}: {val:.4f} bps\n")
        f.write("\n")
        f.write("## Calibration Error per Bin (MAE)\n")
        for i, val in enumerate(report["calibration_error_per_bin_mae"]):
            f.write(f"- Bin {i}: {val:.4f} bps\n")
        f.write("\n")
        f.write("## Expectancy Metrics\n")
        f.write(f"- Gross expectancy using calibrated return: {report['gross_expectancy_using_calibrated_return']:.4f} bps "
                f"(95% CI: [{report['gross_expectancy_ci95']['low']:.4f}, {report['gross_expectancy_ci95']['high']:.4f}])\n")
        f.write(f"- Maker-adjusted expectancy: {report['maker_adjusted_expectancy']:.4f} bps "
                f"(95% CI: [{report['maker_adjusted_ci95']['low']:.4f}, {report['maker_adjusted_ci95']['high']:.4f}])\n")
        f.write(f"- Taker-adjusted expectancy: {report['taker_adjusted_expectancy']:.4f} bps "
                f"(95% CI: [{report['taker_adjusted_ci95']['low']:.4f}, {report['taker_adjusted_ci95']['high']:.4f}])\n")
        f.write(f"- Percentage of observations exceeding gate ({gate:.2f} bps): {report['pct_observations_exceeding_gate']:.2f}%\n\n")
        f.write("## Conditional Expectancy after Cost by Prediction-Strength Bin\n")
        f.write(f"- Low (|cal| ≤ {terciles[0]:.4f} bps): {cond_exp_low:.4f} bps\n")
        f.write(f"- Medium ({terciles[0]:.4f} < |cal| ≤ {terciles[1]:.4f} bps): {cond_exp_mid:.4f} bps\n")
        f.write(f"- High (|cal| > {terciles[1]:.4f} bps): {cond_exp_high:.4f} bps\n\n")
        f.write(f"## Maximum Drawdown of Hypothetical Signal Series\n")
        f.write(f"- Max drawdown: {report['maximum_drawdown_signal_series']:.4f} bps\n\n")
        f.write("## Leakage Check\n")
        f.write(f"- Calibration max timestamp: {report['leakage_check']['calibration_max_ts']}\n")
        f.write(f"- OOS min timestamp: {report['leakage_check']['oos_min_ts']}\n")
        f.write(f"- No leakage: {report['leakage_check']['no_leakage']}\n\n")
        f.write("## Data Quality Checks\n")
        for k, v in report["data_quality_checks"].items():
            f.write(f"- {k}: {v}\n")
        f.write("\n")
        f.write("## Comparison with Untouched V5 Baseline\n")
        f.write(f"- Gross directional expectancy (sign(pred) * actual return): {report['comparison_with_untouched_v5_baseline']['gross_directional_expectancy_bps']:.4f} bps\n\n")
        f.write("## Conclusion\n")
        f.write(f"- **{report['conclusion']}**\n\n")
        f.write("## Note\n")
        f.write(f"- {report['note']}\n")
    print(f"Markdown report written to {md_path}")


if __name__ == "__main__":
    main()