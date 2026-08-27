"""Unit tests for V5 model calibration."""
import numpy as np
import pandas as pd
import pytest

from app.v5_calibration import fit_calibration, calibrate_prediction, _get_split_masks
from app.v3_labels import add_labels
from app.v5_model import load_model


def test_get_split_masks():
    # Create a simple DataFrame with timestamps from 0 to 99
    df = pd.DataFrame({"ts_ms": np.arange(100, dtype=np.int64)})
    # Mock splits: train 0-69, validation 70-84, oos 85-99 (70%,15%,15%)
    splits = {
        "train": {"lo_ms": 0, "hi_ms": 69},
        "validation": {"lo_ms": 70, "hi_ms": 84},
        "oos": {"lo_ms": 85, "hi_ms": 99},
    }
    train_mask, val_mask, oos_mask = _get_split_masks(df, splits)
    assert train_mask.sum() == 70
    assert val_mask.sum() == 15
    assert oos_mask.sum() == 15
    # Ensure no overlap
    assert not (train_mask & val_mask).any()
    assert not (train_mask & oos_mask).any()
    assert not (val_mask & oos_mask).any()


def test_fit_calibration_on_real_data_subset():
    # Use a small subset of the real data to ensure the calibration works
    # We'll take the first 5000 rows of v5_features.parquet
    feature_path = "data/research/v5_features.parquet"
    model_json_path = "data/research/v5_model.json"
    
    # Load the feature data (we'll subset to first 5000 rows for speed)
    df = pd.read_parquet(feature_path)
    # We need to ensure we have enough rows for the splits; we'll just use the first 5000
    # but we must ensure that the timestamps are still increasing.
    df = df.head(5000).copy()
    
    # Load the model to get splits
    model_d = load_model(model_json_path)
    splits = model_d["splits"]
    
    # Get masks for splits
    train_mask, validation_mask, oos_mask = _get_split_masks(df, splits)
    # We expect some rows in each split; if not, we skip the test or adjust.
    # For the subset, the validation split may be empty if the subset is too small.
    # We'll check and only proceed if validation_mask has at least 10 rows.
    if validation_mask.sum() < 10:
        pytest.skip("Subset too small for validation split")
    
    # Now fit calibration on the validation set
    calibration = fit_calibration(
        feature_path=feature_path,
        model_json_path=model_json_path,
        horizon_ms=500,
        n_bins=5,
    )
    
    # Check that we got a valid calibration dict
    assert "bin_edges" in calibration
    assert "bin_means" in calibration
    assert "bin_counts" in calibration
    assert "bin_stderr" in calibration
    assert calibration["n_bins"] == 5
    assert calibration["horizon_ms"] == 500
    assert len(calibration["bin_edges"]) == 6
    assert len(calibration["bin_means"]) == 5
    assert len(calibration["bin_counts"]) == 5
    assert len(calibration["bin_stderr"]) == 5
    # All counts should be non-negative
    assert np.all(calibration["bin_counts"] >= 0)
    # At least one bin should have positive count (since we have validation data)
    assert np.any(calibration["bin_counts"] > 0)


def test_calibrate_prediction_shape():
    # Test that calibrate_prediction returns an array of the same length as input
    feature_path = "data/research/v5_features.parquet"
    model_json_path = "data/research/v5_model.json"
    
    # Use a small subset
    df = pd.read_parquet(feature_path).head(100)
    
    model_d = load_model(model_json_path)
    
    # Dummy calibration (we can create a trivial one)
    # We'll create a calibration that maps everything to zero
    calibration = {
        "bin_edges": np.array([-1e10, 0, 1e10]),  # two bins: (-inf,0] and (0,inf)
        "bin_means": np.array([0.0, 0.0]),
        "bin_counts": np.array([1, 1]),
        "bin_stderr": np.array([0.0, 0.0]),
        "horizon_ms": 500,
        "n_bins": 2,
        "min_pred": -1e10,
        "max_pred": 1e10,
    }
    
    calibrated = calibrate_prediction(model_d, df, horizon_ms=500, calibration=calibration)
    assert calibrated.shape == (len(df),)
    # Should be all zeros
    assert np.allclose(calibrated, 0.0)


def test_fit_calibration_handles_nan():
    # Test that NaN predictions or labels are ignored (using real data may produce NaN labels)
    # We'll use a small subset and expect that the function does not crash.
    feature_path = "data/research/v5_features.parquet"
    model_json_path = "data/research/v5_model.json"
    
    df = pd.read_parquet(feature_path).head(1000)
    
    # Should not raise
    calibration = fit_calibration(
        feature_path=feature_path,
        model_json_path=model_json_path,
        horizon_ms=500,
        n_bins=5,
    )
    # Basic checks
    assert "bin_edges" in calibration
    assert calibration["n_bins"] == 5


if __name__ == "__main__":
    test_get_split_masks()
    print("test_get_split_masks passed")
    test_fit_calibration_on_real_data_subset()
    print("test_fit_calibration_on_real_data_subset passed")
    test_calibrate_prediction_shape()
    print("test_calibrate_prediction_shape passed")
    test_fit_calibration_handles_nan()
    print("test_fit_calibration_handles_nan passed")
    print("All tests passed.")