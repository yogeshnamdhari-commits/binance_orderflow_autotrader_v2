"""End-to-end, research-only V10 fold evaluation.

This module intentionally contains no order-placement code. It wires the
train-only calibration components to chronological OOS evaluation and returns
fold-level diagnostics suitable for an auditable research report.
"""
from __future__ import annotations
import pandas as pd

from .v10_execution_research import evaluate_execution_fold
from .v10_mm_walkforward import make_splits


def run_walkforward(
    observations: pd.DataFrame,
    *,
    train_size: int,
    embargo: int,
    test_size: int,
    step: int,
    bins,
    survival_horizon: float,
    spread_capture_bps: float,
    fee_rebate_bps: float,
    inventory_cost_bps: float,
    exit_cost_bps: float,
    cancellation_cost_bps: float,
) -> list[dict[str, float | int | str]]:
    """Evaluate only chronological OOS folds; all calibration is fit on train."""
    if not isinstance(observations.index, pd.DatetimeIndex):
        raise ValueError("observations index must be a DatetimeIndex")
    if observations.empty:
        raise ValueError("observations must be non-empty")
    results: list[dict[str, float | int | str]] = []
    for fold_id, (train_idx, test_idx) in enumerate(
        make_splits(observations.index, train_size, embargo, test_size, step), start=1
    ):
        train = observations.loc[train_idx]
        test = observations.loc[test_idx]
        metrics = evaluate_execution_fold(
            train,
            test,
            bins=bins,
            survival_horizon=survival_horizon,
            spread_capture_bps=spread_capture_bps,
            fee_rebate_bps=fee_rebate_bps,
            inventory_cost_bps=inventory_cost_bps,
            exit_cost_bps=exit_cost_bps,
            cancellation_cost_bps=cancellation_cost_bps,
        )
        results.append({
            "fold": fold_id,
            "train_start": train_idx[0].isoformat(),
            "train_end": train_idx[-1].isoformat(),
            "oos_start": test_idx[0].isoformat(),
            "oos_end": test_idx[-1].isoformat(),
            **metrics,
        })
    if not results:
        raise ValueError("no walk-forward folds can be formed from observations")
    return results
