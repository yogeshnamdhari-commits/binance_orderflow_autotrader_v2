"""Walk-forward fold economics with fill calibration fit strictly on training data."""
from __future__ import annotations
import numpy as np
import pandas as pd
from .v10_conditional_fill import fit_queue_binned_fill_rates, predict_queue_binned_fill_rate
from .v10_passive_simulator import simulate_passive_order


def evaluate_oos_fold(train: pd.DataFrame, test: pd.DataFrame, bins, spread_capture_bps: float,
                      fee_rebate_bps: float, inventory_cost_bps: float, exit_cost_bps: float,
                      cancellation_cost_bps: float) -> dict[str, float | int]:
    required_train = {"queue_ahead", "filled"}
    required_test = {"queue_ahead", "fill_fraction", "adverse_selection_bps"}
    if not required_train.issubset(train.columns) or not required_test.issubset(test.columns):
        raise ValueError("missing required fold columns")
    if train.empty or test.empty:
        raise ValueError("train and test must be non-empty")
    model = fit_queue_binned_fill_rates(train, bins=bins)
    predicted = predict_queue_binned_fill_rate(model, test["queue_ahead"].to_numpy())
    realized = test["fill_fraction"].to_numpy(float)
    adverse = test["adverse_selection_bps"].to_numpy(float)
    ev = []
    for p, f, a in zip(predicted, realized, adverse):
        result = simulate_passive_order(
            fill_fraction=float(f),
            spread_capture_bps=spread_capture_bps,
            fee_rebate_bps=fee_rebate_bps,
            adverse_selection_bps=float(a),
            inventory_cost_bps=inventory_cost_bps,
            exit_cost_bps=exit_cost_bps,
            cancellation_cost_bps=cancellation_cost_bps,
        )
        ev.append(result["net_ev_bps"])
    return {
        "oos_orders": int(len(test)),
        "train_fill_rate": float(np.mean(train["filled"].to_numpy(int))),
        "oos_realized_fill_rate": float(np.mean(realized > 0)),
        "mean_predicted_fill_probability": float(np.mean(predicted)),
        "mean_oos_ev_bps": float(np.mean(ev)),
        "mean_oos_adverse_selection_bps": float(np.mean(adverse[realized > 0])) if np.any(realized > 0) else float("nan"),
    }
