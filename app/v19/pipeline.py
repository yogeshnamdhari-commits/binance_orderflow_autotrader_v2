from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Sequence
import json

import numpy as np

from .config import V19Config
from .gate import GateResult, evaluate_gate, run_cost_stress
from .walk_forward import FoldResult, evaluate_fold, make_purged_splits


def run_forward_pipeline(
    X: np.ndarray,
    forward_returns_bps: Sequence[float],
    fills: Sequence[int],
    timestamps_ns: Sequence[int],
    config: V19Config,
) -> dict[str, object]:
    """Run locked expanding walk-forward evaluation on a prepared causal feature matrix."""
    splits = make_purged_splits(
        timestamps_ns,
        config.min_train_events,
        config.min_test_events,
        config.embargo_events,
    )
    folds: list[FoldResult] = [
        evaluate_fold(X, forward_returns_bps, fills, timestamps_ns, split, config)
        for split in splits
    ]
    expected = np.asarray([x for fold in folds for x in fold.expected_net_bps], dtype=float)
    realized = np.asarray([x for fold in folds for x in fold.realized_net_bps], dtype=float)
    if expected.size == 0:
        raise ValueError("walk-forward produced no test outcomes")
    # Chronological blocks are the individual walk-forward folds.
    regimes = [np.asarray(fold.expected_net_bps, dtype=float) for fold in folds]
    stress = run_cost_stress(expected, config.cost_stress_multipliers)
    gate = evaluate_gate(expected, realized, regimes, stress)
    return {
        "config_hash": config.config_hash,
        "n_folds": len(folds),
        "n_test_events": int(expected.size),
        "net_ev_bps": gate.net_ev_bps,
        "realized_net_ev_bps": gate.realized_net_ev_bps,
        "ci_low_bps": gate.ci_low_bps,
        "ci_high_bps": gate.ci_high_bps,
        "p_value": gate.p_value,
        "regime_means": list(gate.regime_means),
        "cost_stress": {str(k): v for k, v in gate.cost_stress.items()},
        "gate_pass": gate.passed,
        "gate_reasons": list(gate.reasons),
        "live_order_submission": False,
    }


def write_evidence(result: dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
