#!/usr/bin/env python3
"""
V6 Model — Nonlinear Order-Flow Expected Return Model

Research candidate per staged architecture: small feed-forward network
using OFI/MLOFI features + interaction terms.

Research basis:
- Kolm, Turiel & Westray (2021) "Deep Order Flow Imbalance" — stationary 
  order-flow-derived inputs can outperform raw order-book states for 
  high-frequency return prediction
- Cont, Kukanov & Stoikov — OFI relationship with price impact, nonlinear 
  effects at short horizons

Architecture: 2 hidden layers (32, 16 units), ReLU, dropout, L2 regularization
Input: 17 V5 features + 8 interaction features = 25 features
Output: Expected return in bps over 500ms horizon

Uses scikit-learn MLPRegressor (no PyTorch dependency).
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional
import joblib

from .v5_features import V5_FEATURES, HORIZONS_MS
from .v3_model import chrono_split_masks, SPLIT_FRACTIONS
from .v3_labels import add_labels

try:
    from sklearn.neural_network import MLPRegressor
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False


# V6 Feature Engineering
V5_FEATURES = ["ofi_l1", "ofi_norm_l1", "qi_l1", "di_l5", "di_l10",
               "mpd_bps", "spread_bps", "bid_cancel_bps", "ask_add_bps",
               "cancel_pressure", "tfi_500", "liq_depletion",
               "log_depth1", "log_depth5", "log_event_rate",
               "depth_slope_bps", "vol_500"]

# Interaction features (domain-motivated)
V6_INTERACTION_FEATURES = [
    "ofi_x_depth1",        # OFI × depth1 (impact × liquidity)
    "ofi_x_vol500",        # OFI × volatility (impact × uncertainty)
    "imbalance5_x_spread", # imbalance × spread (adverse selection proxy)
    "ofi_x_qi",            # OFI × queue imbalance
    "tfi500_x_liqdep",     # trade flow × liquidity depletion
    "ofi_x_tfi500",        # OFI × trade flow interaction
    "di5_x_spread",        # depth imbalance × spread
    "vol500_x_spread",     # vol × spread (volatility-spread coupling)
]

V6_FEATURES = ["ofi_l1", "ofi_norm_l1", "qi_l1", "di_l5", "di_l10",
               "mpd_bps", "spread_bps", "bid_cancel_bps", "ask_add_bps",
               "cancel_pressure", "tfi_500", "liq_depletion",
               "log_depth1", "log_depth5", "log_event_rate",
               "depth_slope_bps", "vol_500",
               "ofi_x_depth1", "ofi_x_vol500", "imbalance5_x_spread",
               "ofi_x_qi", "tfi500_x_liqdep", "ofi_x_tfi500",
               "di5_x_spread", "vol500_x_spread"]

PRIMARY_HORIZON = 500


def add_interaction_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add interaction features to dataframe (causal, no leakage)."""
    df = df.copy()
    
    # Need depth1 for OFI × depth1 interaction
    # Approximate from log_depth1: depth1 ≈ exp(log_depth1) - 1
    if "log_depth1" in df.columns:
        df["depth1_approx"] = np.expm1(df["log_depth1"])
    else:
        df["depth1_approx"] = 1.0
    
    # Interaction features
    df["ofi_x_depth1"] = df["ofi_l1"] * df["depth1_approx"]
    df["ofi_x_vol500"] = df["ofi_l1"] * df["vol_500"]
    df["imbalance5_x_spread"] = df["di_l5"] * df["spread_bps"]
    df["ofi_x_qi"] = df["ofi_l1"] * df["qi_l1"]
    df["tfi500_x_liqdep"] = df["tfi_500"] * df["liq_depletion"]
    df["ofi_x_tfi500"] = df["ofi_l1"] * df["tfi_500"]
    df["di5_x_spread"] = df["di_l5"] * df["spread_bps"]
    df["vol500_x_spread"] = df["vol_500"] * df["spread_bps"]
    
    # Replace inf/nan with 0
    for col in [
        "ofi_x_depth1", "ofi_x_vol500", "imbalance5_x_spread",
        "ofi_x_qi", "tfi500_x_liqdep", "ofi_x_tfi500",
        "di5_x_spread", "vol500_x_spread"
    ]:
        if col in df.columns:
            df[col] = df[col].replace([np.inf, -np.inf], 0).fillna(0)
    
    return df


def prepare_v6_data(feature_path: str | Path, horizon_ms: int = 500) -> Tuple[pd.DataFrame, np.ndarray, np.ndarray, np.ndarray]:
    """Load features, add interactions, add labels, return splits."""
    df = pd.read_parquet(feature_path)
    df = add_labels(df, horizons=(horizon_ms,))
    df = add_interaction_features(df)
    
    # Filter valid rows
    required = [
        "ofi_l1", "ofi_norm_l1", "qi_l1", "di_l5", "di_l10",
        "mpd_bps", "spread_bps", "bid_cancel_bps", "ask_add_bps",
        "cancel_pressure", "tfi_500", "liq_depletion",
        "log_depth1", "log_depth5", "log_event_rate",
        "depth_slope_bps", "vol_500",
        "ofi_x_depth1", "ofi_x_vol500", "imbalance5_x_spread",
        "ofi_x_qi", "tfi500_x_liqdep", "ofi_x_tfi500",
        "di5_x_spread", "vol500_x_spread",
        f"r_{horizon_ms}", "ts_ms", "mid", "spread_bps", "regime"
    ]
    mask = (
        df["mid"].notna() & (df["mid"] > 0) &
        df["spread_bps"].notna() & (df["spread_bps"] > 0) &
        df["regime"].isin(["normal", "high_impact", "thin_book"]) &
        df[[
            "ofi_l1", "ofi_norm_l1", "qi_l1", "di_l5", "di_l10",
            "mpd_bps", "spread_bps", "bid_cancel_bps", "ask_add_bps",
            "cancel_pressure", "tfi_500", "liq_depletion",
            "log_depth1", "log_depth5", "log_event_rate",
            "depth_slope_bps", "vol_500",
            "ofi_x_depth1", "ofi_x_vol500", "imbalance5_x_spread",
            "ofi_x_qi", "tfi500_x_liqdep", "ofi_x_tfi500",
            "di5_x_spread", "vol500_x_spread"
        ]].notna().all(axis=1)
    )
    
    # Split
    splits = chrono_split_masks(df)
    train_mask = splits[0]["mask"]
    val_mask = splits[1]["mask"]
    oos_mask = splits[2]["mask"]
    
    return df, train_mask, val_mask, oos_mask


class V6Model:
    """V6 Nonlinear Order-Flow Model wrapper using sklearn MLPRegressor."""
    
    def __init__(self, model_path: Optional[str] = None):
        self.pipeline = None
        self.feature_names = [
            "ofi_l1", "ofi_norm_l1", "qi_l1", "di_l5", "di_l10",
            "mpd_bps", "spread_bps", "bid_cancel_bps", "ask_add_bps",
            "cancel_pressure", "tfi_500", "liq_depletion",
            "log_depth1", "log_depth5", "log_event_rate",
            "depth_slope_bps", "vol_500",
            "ofi_x_depth1", "ofi_x_vol500", "imbalance5_x_spread",
            "ofi_x_qi", "tfi500_x_liqdep", "ofi_x_tfi500",
            "di5_x_spread", "vol500_x_spread"
        ]
        
        if model_path and Path(model_path).exists():
            self.load(model_path)
    
    def fit(self, feature_path: str | Path, horizon_ms: int = 500, 
            out_dir: Optional[str] = None) -> Dict:
        """Train V6 model on chronological train split."""
        if not SKLEARN_AVAILABLE:
            raise RuntimeError("scikit-learn not available.")
        
        # Prepare data
        df, train_mask, val_mask, oos_mask = prepare_v6_data(feature_path)
        
        # Prepare data arrays
        feature_cols = [
            "ofi_l1", "ofi_norm_l1", "qi_l1", "di_l5", "di_l10",
            "mpd_bps", "spread_bps", "bid_cancel_bps", "ask_add_bps",
            "cancel_pressure", "tfi_500", "liq_depletion",
            "log_depth1", "log_depth5", "log_event_rate",
            "depth_slope_bps", "vol_500",
            "ofi_x_depth1", "ofi_x_vol500", "imbalance5_x_spread",
            "ofi_x_qi", "tfi500_x_liqdep", "ofi_x_tfi500",
            "di5_x_spread", "vol500_x_spread"
        ]
        X = df[feature_cols].to_numpy(float)
        y = df["r_500"].to_numpy(float)
        
        # Filter finite
        finite = np.isfinite(X).all(axis=1) & np.isfinite(df["r_500"].to_numpy(float))
        X = X[finite]
        y = df["r_500"].to_numpy(float)[finite]
        
        # Apply same filter to masks
        train_mask = train_mask[finite]
        val_mask = val_mask[finite]
        oos_mask = oos_mask[finite]
        
        X_train, y_train = X[train_mask], y[train_mask]
        X_val, y_val = X[val_mask], y[val_mask]
        X_oos, y_oos = X[oos_mask], y[oos_mask]
        
        # Create pipeline with scaler + MLP
        from sklearn.neural_network import MLPRegressor
        from sklearn.preprocessing import StandardScaler
        from sklearn.pipeline import Pipeline
        
        self.pipeline = Pipeline([
            ('scaler', StandardScaler()),
            ('mlp', MLPRegressor(
                hidden_layer_sizes=(32, 16),
                activation='relu',
                alpha=1e-4,
                learning_rate_init=1e-3,
                batch_size=256,
                max_iter=200,
                early_stopping=True,
                validation_fraction=0.15,
                n_iter_no_change=10,
                random_state=42,
                verbose=False
            ))
        ])
        
        # Train
        self.pipeline.fit(X[train_mask], y[train_mask])
        
        # Evaluate on OOS
        oos_pred = self.pipeline.predict(X[oos_mask])
        y_oos = y[oos_mask]
        
        # Metrics
        oos_mse = float(np.mean((y_oos - oos_pred)**2))
        oos_mae = float(np.mean(np.abs(y_oos - oos_pred)))
        oos_corr = float(np.corrcoef(y_oos, oos_pred)[0,1]) if len(y_oos) > 1 else 0.0
        
        # Save if requested
        if out_dir:
            self.save(out_dir)
        
        return {
            "train_size": int(train_mask.sum()),
            "val_size": int(val_mask.sum()),
            "oos_size": int(oos_mask.sum()),
            "oos_mse": float(oos_mse),
            "oos_mae": float(oos_mae),
            "oos_corr": float(oos_corr),
        }
    
    def predict(self, df: pd.DataFrame) -> np.ndarray:
        """Predict expected return in bps."""
        if self.pipeline is None:
            raise RuntimeError("Model not trained or loaded.")
        feature_cols = [
            "ofi_l1", "ofi_norm_l1", "qi_l1", "di_l5", "di_l10",
            "mpd_bps", "spread_bps", "bid_cancel_bps", "ask_add_bps",
            "cancel_pressure", "tfi_500", "liq_depletion",
            "log_depth1", "log_depth5", "log_event_rate",
            "depth_slope_bps", "vol_500",
            "ofi_x_depth1", "ofi_x_vol500", "imbalance5_x_spread",
            "ofi_x_qi", "tfi500_x_liqdep", "ofi_x_tfi500",
            "di5_x_spread", "vol500_x_spread"
        ]
        X = df[feature_cols].to_numpy(float)
        return self.pipeline.predict(X)
    
    def save(self, out_dir: str):
        """Save model and metadata."""
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        
        joblib.dump(self.pipeline, out_path / "v6_model.joblib")
        
        # Save metadata as JSON
        meta = {
            "model_type": "V6_MLPRegressor",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "features": [
                "ofi_l1", "ofi_norm_l1", "qi_l1", "di_l5", "di_l10",
                "mpd_bps", "spread_bps", "bid_cancel_bps", "ask_add_bps",
                "cancel_pressure", "tfi_500", "liq_depletion",
                "log_depth1", "log_depth5", "log_event_rate",
                "depth_slope_bps", "vol_500",
                "ofi_x_depth1", "ofi_x_vol500", "imbalance5_x_spread",
                "ofi_x_qi", "tfi500_x_liqdep", "ofi_x_tfi500",
                "di5_x_spread", "vol500_x_spread"
            ],
            "base_features": [
                "ofi_l1", "ofi_norm_l1", "qi_l1", "di_l5", "di_l10",
                "mpd_bps", "spread_bps", "bid_cancel_bps", "ask_add_bps",
                "cancel_pressure", "tfi_500", "liq_depletion",
                "log_depth1", "log_depth5", "log_event_rate",
                "depth_slope_bps", "vol_500"
            ],
            "interaction_features": [
                "ofi_x_depth1", "ofi_x_vol500", "imbalance5_x_spread",
                "ofi_x_qi", "tfi500_x_liqdep", "ofi_x_tfi500",
                "di5_x_spread", "vol500_x_spread"
            ],
            "horizon_ms": 500,
            "hyperparams": {
                "hidden_layers": [32, 16],
                "alpha": 1e-4,
                "learning_rate_init": 1e-3,
                "batch_size": 256,
                "max_iter": 200,
                "early_stopping": True,
                "validation_fraction": 0.15,
            },
            "split_fractions": [0.7, 0.15, 0.15],
        }
        (Path(out_dir) / "v6_model.json").write_text(json.dumps(meta, indent=1))
    
    def load(self, model_path: str):
        """Load model."""
        self.pipeline = joblib.load(model_path)
        # Load metadata
        meta_path = Path(model_path).parent / "v6_model.json"
        if meta_path.exists():
            with open(meta_path) as f:
                meta = json.load(f)
                self.feature_names = meta.get("features", [])


def train_v6_model(feature_path: str | Path, out_dir: str | Path) -> Dict:
    """Train V6 model and save to out_dir."""
    if not SKLEARN_AVAILABLE:
        raise RuntimeError("scikit-learn not available.")
    
    model = V6Model()
    return model.fit(feature_path, out_dir=out_dir)


def load_v6_model(model_dir: str | Path) -> V6Model:
    """Load trained V6 model."""
    model_path = Path(model_dir) / "v6_model.joblib"
    return V6Model(str(model_path))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", type=Path, default=Path("data/research/v5_features.parquet"))
    ap.add_argument("--out", type=Path, default=Path("data/research/v6_model"))
    a = ap.parse_args()
    
    if not SKLEARN_AVAILABLE:
        print("scikit-learn not available. Install with: pip install scikit-learn")
        exit(1)
    
    print("Training V6 model...")
    metrics = train_v6_model(a.features, a.out)
    print(f"Training complete: {metrics}")


def load_model(model_dir: str | Path) -> V6Model:
    """Load trained V6 model from directory."""
    return load_v6_model(model_dir)


def predict(model: V6Model, df: pd.DataFrame) -> np.ndarray:
    """Predict using V6 model."""
    return model.predict(df)