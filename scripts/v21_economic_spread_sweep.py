"""Nested walk-forward economic spread selection for the V21 learned maker.

This research-only sweep does not alter production configuration. For each outer
test session, it selects a half-spread using the immediately preceding session's
second half as an inner validation set, while models are trained only on earlier
session first halves. The selected spread is then evaluated once on the untouched
outer test half.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.v21_learned_market_maker import (
    _build_models,
    replay_test_session,
)


SPREAD_GRID_BPS = (0.50, 0.75, 1.00, 1.25, 1.50, 1.75, 2.25, 2.50)


def run(captures_root: Path, dataset_path: Path, toxicity_path: Path) -> dict[str, Any]:
    dataset = pd.read_parquet(dataset_path)
    toxicity = pd.read_parquet(toxicity_path)
    sessions = sorted(dataset["session"].unique().tolist())

    outer: dict[str, Any] = {}
    for i in range(1, len(sessions)):
        test_session = sessions[i]
        train_sessions = sessions[:i]
        inner_session = train_sessions[-1]

        models, sizes = _build_models(dataset, toxicity, train_sessions)

        selection: dict[str, dict[str, Any]] = {}
        for spread in SPREAD_GRID_BPS:
            result = replay_test_session(
                captures_root / inner_session,
                inner_session,
                models,
                half_spread_bps=spread,
            )
            selection[f"{spread:.2f}"] = {
                "half_spread_bps": spread,
                "net_pnl_usd": result["net_pnl_usd"],
                "baseline_net_pnl_usd": result["baseline_net_pnl_usd"],
                "improvement_vs_fixed_baseline_usd": result["improvement_vs_fixed_baseline_usd"],
                "fills": result["stats"]["fills"],
                "filled_qty": result["stats"]["filled_qty"],
                "fees_usd": result["fees_usd"],
                "final_inventory": result["final_inventory"],
                "test_depth_events": result["test_depth_events"],
                "test_trade_events": result["test_trade_events"],
            }

        eligible = [
            v for v in selection.values()
            if int(v["fills"]) > 0
        ]
        if not eligible:
            eligible = list(selection.values())

        selected = max(
            eligible,
            key=lambda v: (
                float(v["improvement_vs_fixed_baseline_usd"]),
                int(v["fills"]),
                -abs(float(v["final_inventory"])),
                -float(v["half_spread_bps"]),
            ),
        )

        test_result = replay_test_session(
            captures_root / test_session,
            test_session,
            models,
            half_spread_bps=float(selected["half_spread_bps"]),
        )

        outer[test_session] = {
            "training_sessions": train_sessions,
            "training_sizes": sizes,
            "inner_validation_session": inner_session,
            "spread_grid_bps": list(SPREAD_GRID_BPS),
            "selected": selected,
            "outer_test": {
                "half_spread_bps": float(selected["half_spread_bps"]),
                "net_pnl_usd": test_result["net_pnl_usd"],
                "baseline_net_pnl_usd": test_result["baseline_net_pnl_usd"],
                "improvement_vs_fixed_baseline_usd": test_result["improvement_vs_fixed_baseline_usd"],
                "fills": test_result["stats"]["fills"],
                "filled_qty": test_result["stats"]["filled_qty"],
                "fees_usd": test_result["fees_usd"],
                "final_inventory": test_result["final_inventory"],
                "quote_enabled": test_result["stats"]["quote_enabled"],
                "toxicity_suppressed": test_result["stats"]["toxicity_suppressed"],
                "test_depth_events": test_result["test_depth_events"],
                "test_trade_events": test_result["test_trade_events"],
            },
            "inner_selection_results": selection,
        }

    return {
        "protocol": (
            "nested walk-forward: train on prior-session first halves; "
            "select spread on immediately prior-session second half; "
            "evaluate selected spread on untouched outer-session second half"
        ),
        "spread_grid_bps": list(SPREAD_GRID_BPS),
        "sessions": sessions,
        "folds": outer,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--captures-root", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--toxicity", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = run(args.captures_root, args.dataset, args.toxicity)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
