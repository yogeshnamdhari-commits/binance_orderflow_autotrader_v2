"""Leakage-safe integration of replayed passive-order outcomes for V10 research."""
from __future__ import annotations
import numpy as np
import pandas as pd


def build_execution_observations(events: pd.DataFrame, horizon: int) -> pd.DataFrame:
    required = {"timestamp", "mid", "side", "fill_fraction", "queue_ahead"}
    missing = required - set(events.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    if int(horizon) <= 0:
        raise ValueError("horizon must be positive")
    df = events.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    if df.empty or df["timestamp"].duplicated().any() or not df["timestamp"].is_monotonic_increasing:
        raise ValueError("events must be non-empty, sorted, and duplicate-free")
    if not np.all(np.isfinite(df["mid"])) or np.any(df["mid"] <= 0):
        raise ValueError("mid must be finite and positive")
    if not np.all(np.isfinite(df["fill_fraction"])) or np.any((df["fill_fraction"] < 0) | (df["fill_fraction"] > 1)):
        raise ValueError("fill_fraction must be in [0,1]")
    if not np.all(np.isfinite(df["queue_ahead"])) or np.any(df["queue_ahead"] < 0):
        raise ValueError("queue_ahead must be finite and non-negative")
    if not df["side"].isin(["bid", "ask"]).all():
        raise ValueError("side must be bid or ask")
    df["post_mid"] = df["mid"].shift(-int(horizon))
    out = df.iloc[:-int(horizon)].copy()
    signed = np.where(out["side"].eq("ask"), 1.0, -1.0)
    out["adverse_selection_bps"] = ((out["post_mid"] / out["mid"] - 1.0) * signed * 10_000.0)
    return out


def summarize_execution_economics(observations: pd.DataFrame) -> dict[str, float | int]:
    required = {"fill_fraction", "adverse_selection_bps", "queue_ahead"}
    missing = required - set(observations.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    if observations.empty:
        raise ValueError("observations must be non-empty")
    f = observations["fill_fraction"].to_numpy(float)
    a = observations["adverse_selection_bps"].to_numpy(float)
    if not np.all(np.isfinite(f)) or not np.all(np.isfinite(a)):
        raise ValueError("metrics must be finite")
    return {
        "orders": int(len(observations)),
        "filled_orders": int(np.count_nonzero(f > 0)),
        "fill_rate": float(np.mean(f > 0)),
        "mean_fill_fraction": float(np.mean(f)),
        "mean_adverse_selection_bps": float(np.mean(a[f > 0])) if np.any(f > 0) else float("nan"),
        "median_queue_ahead": float(np.median(observations["queue_ahead"])),
    }
