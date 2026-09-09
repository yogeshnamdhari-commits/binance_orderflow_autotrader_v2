"""V16 pre-registered robustness checks."""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_TRADES = 100
N_BLOCKS = 5
COST_MULTIPLIERS = (1.0, 1.25)
MIN_POSITIVE_BLOCKS = 4
MIN_POSITIVE_REGIMES = 4

REQUIRED_COLUMNS = {
    "predicted_return_bps",
    "fill_probability",
    "total_cost_bps",
    "expected_pnl_bps",
    "regime",
}


def _finite_trades(trades: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED_COLUMNS.difference(trades.columns)
    if missing:
        raise ValueError(f"missing robustness columns: {sorted(missing)}")
    out = trades.copy()
    numeric = ["predicted_return_bps", "fill_probability", "total_cost_bps", "expected_pnl_bps"]
    out[numeric] = out[numeric].apply(pd.to_numeric, errors="coerce")
    out = out.replace([np.inf, -np.inf], np.nan).dropna(subset=numeric + ["regime"])
    return out.reset_index(drop=True)


def evaluate_robustness(trades: pd.DataFrame) -> dict:
    """Evaluate fixed robustness gates on an ordered forward trade table."""
    try:
        df = _finite_trades(trades)
    except ValueError as exc:
        return {"status": "BLOCKED", "reason": str(exc)}

    n = len(df)
    if n < MIN_TRADES:
        return {"status": "BLOCKED", "reason": f"insufficient trades: {n} < {MIN_TRADES}"}

    # Preserve chronological order and split by row position, not by NumPy's
    # DataFrame object handling (which can return object arrays rather than frames).
    block_indices = np.array_split(np.arange(n), N_BLOCKS)
    block_means = [float(df.iloc[idx]["expected_pnl_bps"].mean()) for idx in block_indices if len(idx)]
    positive_blocks = sum(x > 0 for x in block_means)
    chronological_pass = positive_blocks >= MIN_POSITIVE_BLOCKS

    stress_rows = []
    for multiplier in COST_MULTIPLIERS:
        stressed = df["fill_probability"] * df["predicted_return_bps"] - multiplier * df["total_cost_bps"]
        stress_rows.append({"cost_multiplier": multiplier, "net_ev_bps": float(stressed.mean())})
    worst_case = float(min(x["net_ev_bps"] for x in stress_rows))
    cost_pass = stress_rows[-1]["net_ev_bps"] > 0

    regimes = sorted(str(x) for x in df["regime"].unique())
    loo = {}
    positive_loo = 0
    for regime in regimes:
        retained = df[df["regime"].astype(str) != regime]
        mean_ev = float(retained["expected_pnl_bps"].mean()) if len(retained) else 0.0
        loo[regime] = {"mean_net_ev_bps": mean_ev, "n": int(len(retained)), "positive": mean_ev > 0}
        positive_loo += int(mean_ev > 0)
    regime_pass = len(regimes) >= 4 and positive_loo >= MIN_POSITIVE_REGIMES

    checks = {
        "chronological_blocks": {
            "n_blocks": N_BLOCKS,
            "block_net_ev_bps": block_means,
            "positive_blocks": positive_blocks,
            "required_positive_blocks": MIN_POSITIVE_BLOCKS,
            "status": "PASS" if chronological_pass else "FAIL",
        },
        "cost_stress": {
            "scenarios": stress_rows,
            "worst_case_net_ev_bps": worst_case,
            "threshold_multiplier": COST_MULTIPLIERS[-1],
            "status": "PASS" if cost_pass else "FAIL",
        },
        "leave_one_regime_out": {
            "regimes": loo,
            "positive_regimes": positive_loo,
            "required_positive_regimes": MIN_POSITIVE_REGIMES,
            "status": "PASS" if regime_pass else "FAIL",
        },
    }
    return {
        "status": "PASS" if chronological_pass and cost_pass and regime_pass else "FAIL",
        "n_trades": n,
        "checks": checks,
        "method": {
            "min_trades": MIN_TRADES,
            "chronological_blocks": N_BLOCKS,
            "cost_multipliers": list(COST_MULTIPLIERS),
            "no_parameter_search": True,
        },
    }
