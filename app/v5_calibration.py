"""V5 model calibration: map frozen V5 predictions to calibrated expected return (bps).

Uses binned calibration on a chronological calibration set (middle 15% by timestamp)
to produce a piecewise-constant mapping from V5 model prediction (bps) to
empirical expected future return (bps) over the V5 model's primary horizon (500 ms).
"""
import json
from pathlib import Path
from typing import Dict, Tuple, Optional

import numpy as np
import pandas as pd

from .v3_labels import add_labels
from .v5_model import load_model, predict


def _load_v5_model_json(model_json_path: Path = Path("data/research/v5_model.json")) -> dict:
    """Load the frozen V5 model JSON containing splits and coefficients."""
    with open(model_json_path) as f:
        return json.load(f)


def _get_split_masks(df: pd.DataFrame, splits: dict) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return boolean masks for train, validation, oos splits based on timestamps in splits.
    
    Args:
        df: DataFrame with a 'ts_ms' column (int64).
        splits: dict as loaded from v5_model.json['splits'].
        
    Returns:
        Tuple (train_mask, validation_mask, oos_mask) as boolean numpy arrays.
    """
    ts = df["ts_ms"].to_numpy(dtype=np.int64)
    train_mask = (ts >= splits["train"]["lo_ms"]) & (ts <= splits["train"]["hi_ms"])
    validation_mask = (ts >= splits["validation"]["lo_ms"]) & (ts <= splits["validation"]["hi_ms"])
    oos_mask = (ts >= splits["oos"]["lo_ms"]) & (ts <= splits["oos"]["hi_ms"])
    return train_mask, validation_mask, oos_mask


def fit_calibration(
    feature_path: str | Path,
    model_json_path: str | Path = "data/research/v5_model.json",
    horizon_ms: int = 500,
    n_bins: int = 15,
) -> Dict:
    """Fit binned calibration map using the V5 model's validation split.
    
    Args:
        feature_path: Path to the feature parquet file (e.g., v5_features.parquet).
        model_json_path: Path to the frozen V5 model JSON.
        horizon_ms: Horizon for labels (default 500 ms, must match V5 model primary horizon).
        n_bins: Number of equal-width bins for calibration (default 15).
        
    Returns:
        Calibration dict with keys:
            - bin_edges: np.ndarray of length n_bins+1
            - bin_means: np.ndarray of length n_bins (mean actual return per bin)
            - bin_counts: np.ndarray of length n_bins (sample count per bin)
            - bin_stderr: np.ndarray of length n_bins (standard error of the mean per bin)
            - horizon_ms: horizon used
            - n_bins: number of bins
    """
    feature_path = Path(feature_path)
    model_json_path = Path(model_json_path)
    
    # Load features and add labels for the horizon
    df = pd.read_parquet(feature_path)
    df = add_labels(df, horizons=(horizon_ms,))
    label_col = f"r_{horizon_ms}"
    
    # Load V5 model to get the model dict and splits
    model_d = load_model(model_json_path)
    splits = model_d["splits"]
    
    # Get masks for splits
    _, validation_mask, _ = _get_split_masks(df, splits)
    
    # Restrict to calibration (validation) set
    df_cal = df.loc[validation_mask].copy()
    if len(df_cal) == 0:
        raise ValueError("No calibration samples found in validation split")
    
    # Compute V5 model predictions on calibration set
    feature_cols = model_d["features"]
    # Ensure we only use rows with finite features and label
    X = df_cal[feature_cols].to_numpy(float)
    # Predict returns raw V5 model output (in bps)
    pred_raw = predict(model_d, df_cal[feature_cols], horizon_ms)
    # Actual future return in bps
    y_true = df_cal[label_col].to_numpy(float)
    
    # Filter to finite predictions and labels
    finite = np.isfinite(pred_raw) & np.isfinite(y_true)
    pred_raw = pred_raw[finite]
    y_true = y_true[finite]
    
    if len(pred_raw) == 0:
        raise ValueError("No finite predictions and labels in calibration set")
    
    # Determine bin edges from calibration set predictions only (equal-width)
    min_pred = np.min(pred_raw)
    max_pred = np.max(pred_raw)
    # Avoid zero width if all predictions are identical
    if min_pred == max_pred:
        # Expand slightly to create a bin
        min_pred -= 1e-6
        max_pred += 1e-6
    bin_width = (max_pred - min_pred) / n_bins
    bin_edges = np.linspace(min_pred, max_pred, n_bins + 1)
    
    # Assign each prediction to a bin index
    bin_indices = np.floor((pred_raw - min_pred) / bin_width).astype(int)
    # Clamp to valid bin indices [0, n_bins-1]
    bin_indices = np.clip(bin_indices, 0, n_bins - 1)
    
    # Compute bin statistics
    bin_sums = np.zeros(n_bins, dtype=float)
    bin_counts = np.zeros(n_bins, dtype=int)
    bin_sq_sums = np.zeros(n_bins, dtype=float)  # for variance
    
    for idx, pred, y in zip(bin_indices, pred_raw, y_true):
        bin_sums[idx] += y
        bin_counts[idx] += 1
        bin_sq_sums[idx] += y * y
    
    # Compute mean, variance, and standard error
    bin_means = np.zeros(n_bins, dtype=float)
    bin_stderr = np.zeros(n_bins, dtype=float)
    for i in range(n_bins):
        if bin_counts[i] > 0:
            bin_means[i] = bin_sums[i] / bin_counts[i]
            # variance = E[X^2] - E[X]^2
            variance = (bin_sq_sums[i] / bin_counts[i]) - (bin_means[i] ** 2)
            # Ensure variance is non-negative due to floating point
            if variance < 0:
                variance = 0.0
            # standard error = sqrt(variance / n)
            bin_stderr[i] = np.sqrt(variance / bin_counts[i]) if bin_counts[i] > 0 else 0.0
        else:
            bin_means[i] = 0.0
            bin_stderr[i] = 0.0
    
    calibration = {
        "bin_edges": bin_edges,
        "bin_means": bin_means,
        "bin_counts": bin_counts,
        "bin_stderr": bin_stderr,
        "horizon_ms": horizon_ms,
        "n_bins": n_bins,
        "min_pred": float(min_pred),
        "max_pred": float(max_pred),
    }
    return calibration


def calibrate_prediction(
    model_d: dict,
    df: pd.DataFrame,
    horizon_ms: int,
    calibration: Dict,
) -> np.ndarray:
    """Transform V5 model predictions to calibrated expected return using a calibration map.
    
    Args:
        model_d: Loaded V5 model dict (from v5_model.load_model).
        df: DataFrame with features (must include columns in model_d["features"]).
        horizon_ms: Horizon for prediction (must match calibration horizon).
        calibration: Calibration dict returned by fit_calibration.
        
    Returns:
        Calibrated expected return in bps for each row (same length as df).
        Returns NaN for rows with non-finite features or predictions.
    """
    # Ensure horizon matches
    if horizon_ms != calibration["horizon_ms"]:
        raise ValueError(
            f"Horizon mismatch: calibration horizon {calibration['horizon_ms']} "
            f"!= prediction horizon {horizon_ms}"
        )
    
    feature_cols = model_d["features"]
    # Features to numpy
    X = df[feature_cols].to_numpy(float)
    # Predict raw V5 model output
    pred_raw = predict(model_d, df[feature_cols], horizon_ms)
    
    # Prepare output array
    calibrated = np.full(len(df), np.nan, dtype=float)
    
    # Only process finite predictions
    finite = np.isfinite(pred_raw)
    if not np.any(finite):
        return calibrated
    
    pred_finite = pred_raw[finite]
    # Get bin edges and min/max from calibration
    bin_edges = calibration["bin_edges"]
    bin_means = calibration["bin_means"]
    min_pred = calibration["min_pred"]
    max_pred = calibration["max_pred"]
    n_bins = calibration["n_bins"]
    
    # Clip predictions to the calibration range to avoid out-of-range
    pred_clipped = np.clip(pred_finite, min_pred, max_pred)
    
    # Compute bin indices
    bin_width = (max_pred - min_pred) / n_bins
    # Avoid division by zero (should not happen due to clipping and check in fit)
    if bin_width == 0:
        # All predictions are the same; assign to bin 0
        bin_indices = np.zeros(len(pred_finite), dtype=int)
    else:
        bin_indices = np.floor((pred_clipped - min_pred) / bin_width).astype(int)
        # Clamp to valid bin indices (should already be within range due to clipping)
        bin_indices = np.clip(bin_indices, 0, n_bins - 1)
    
    # Assign calibrated values
    calibrated[finite] = bin_means[bin_indices]
    
    return calibrated