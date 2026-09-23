"""Leakage-safe integration of replayed passive-order outcomes for V10 research."""
from __future__ import annotations
import numpy as np
import pandas as pd

from .v10_conditional_fill import fit_queue_binned_fill_rates, predict_queue_binned_fill_rate
from .v10_fill_survival import fit_kaplan_meier
from .v10_passive_simulator import simulate_passive_order


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


def _queue_binned_mean(train: pd.DataFrame, value_col: str, bins, default: float = 0.0):
    edges = tuple(float(x) for x in bins)
    if len(edges) < 2 or any(b <= a for a, b in zip(edges, edges[1:])):
        raise ValueError("bins must be strictly increasing")
    q = train["queue_ahead"].to_numpy(float)
    v = train[value_col].to_numpy(float)
    idx = np.searchsorted(edges, q, side="right") - 1
    out = np.full(len(edges) - 1, float(default), dtype=float)
    for i in range(len(out)):
        mask = (idx == i) & np.isfinite(v)
        if np.any(mask):
            out[i] = float(np.mean(v[mask]))
    return edges, out


def evaluate_execution_fold(
    train: pd.DataFrame,
    test: pd.DataFrame,
    *,
    bins,
    survival_horizon: float,
    spread_capture_bps: float,
    fee_rebate_bps: float,
    inventory_cost_bps: float,
    exit_cost_bps: float,
    cancellation_cost_bps: float,
) -> dict[str, float | int]:
    """Evaluate one chronological OOS fold; no calibration uses test outcomes."""
    required = {"queue_ahead", "filled", "time_to_fill", "adverse_selection_bps"}
    if not required.issubset(train.columns) or not required.issubset(test.columns):
        raise ValueError("train and test must contain queue_ahead, filled, time_to_fill, adverse_selection_bps")
    if "fill_fraction" not in test.columns or train.empty or test.empty:
        raise ValueError("test must contain fill_fraction and both samples must be non-empty")

    fill_model = fit_queue_binned_fill_rates(train, bins=bins)
    predicted_fill = predict_queue_binned_fill_rate(fill_model, test["queue_ahead"].to_numpy())
    _, adverse_rates = _queue_binned_mean(train[train["filled"] == 1], "adverse_selection_bps", bins)

    q = test["queue_ahead"].to_numpy(float)
    idx = np.searchsorted(fill_model.edges, q, side="right") - 1
    predicted_adverse = np.zeros(len(test), dtype=float)
    valid = (idx >= 0) & (idx < len(adverse_rates))
    predicted_adverse[valid] = adverse_rates[idx[valid]]

    km = fit_kaplan_meier(train["time_to_fill"], train["filled"])
    predicted_horizon_fill = km.fill_probability(survival_horizon)

    expected_ev = []
    realized_ev = []
    realized_fill = test["fill_fraction"].to_numpy(float)
    realized_adverse = test["adverse_selection_bps"].to_numpy(float)
    for p, a, f, ar in zip(predicted_fill, predicted_adverse, realized_fill, realized_adverse):
        gross_if_filled = spread_capture_bps + fee_rebate_bps - float(a) - inventory_cost_bps - exit_cost_bps
        expected_ev.append(float(p) * gross_if_filled - cancellation_cost_bps)
        realized_ev.append(simulate_passive_order(
            fill_fraction=float(f),
            spread_capture_bps=spread_capture_bps,
            fee_rebate_bps=fee_rebate_bps,
            adverse_selection_bps=float(ar),
            inventory_cost_bps=inventory_cost_bps,
            exit_cost_bps=exit_cost_bps,
            cancellation_cost_bps=cancellation_cost_bps,
        )["net_ev_bps"])

    return {
        "oos_orders": int(len(test)),
        "train_fill_rate": float(np.mean(train["filled"].to_numpy(int))),
        "oos_realized_fill_rate": float(np.mean(realized_fill > 0)),
        "mean_predicted_fill_probability": float(np.mean(predicted_fill)),
        "predicted_horizon_fill_probability": float(predicted_horizon_fill),
        "mean_predicted_adverse_selection_bps": float(np.mean(predicted_adverse)),
        "mean_oos_expected_ev_bps": float(np.mean(expected_ev)),
        "mean_oos_realized_ev_bps": float(np.mean(realized_ev)),
        "mean_oos_realized_adverse_selection_bps": float(np.mean(realized_adverse[realized_fill > 0])) if np.any(realized_fill > 0) else float("nan"),
    }
