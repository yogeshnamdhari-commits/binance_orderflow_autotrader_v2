"""Nested walk-forward sweep for V21 toxicity/risk gating.

Only research parameters are swept. Training remains on earlier-session first
halves; parameters are selected on the immediately preceding session second
half; selected parameters are evaluated once on the untouched outer test half.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.v21_learned_market_maker import _build_models, replay_test_session


MIN_EDGE_GRID_BPS = (0.10, 0.25, 0.50, 0.75, 1.00)
TOXICITY_MULTIPLIER_GRID = (1.00, 1.25, 1.50, 2.00)
MIN_INNER_FILLS = 2


def run(captures_root: Path, dataset_path: Path, toxicity_path: Path) -> dict[str, Any]:
    dataset = pd.read_parquet(dataset_path)
    toxicity = pd.read_parquet(toxicity_path)
    sessions = sorted(dataset["session"].unique().tolist())
    folds: dict[str, Any] = {}

    for i in range(1, len(sessions)):
        test_session = sessions[i]
        train_sessions = sessions[:i]
        inner_session = train_sessions[-1]
        models, sizes = _build_models(dataset, toxicity, train_sessions)

        selection: list[dict[str, Any]] = []
        for min_edge in MIN_EDGE_GRID_BPS:
            for tox_mult in TOXICITY_MULTIPLIER_GRID:
                result = replay_test_session(
                    captures_root / inner_session,
                    inner_session,
                    models,
                    half_spread_bps=2.5,
                    min_edge_bps=min_edge,
                    toxicity_multiplier=tox_mult,
                )
                selection.append(
                    {
                        "min_edge_bps": min_edge,
                        "toxicity_multiplier": tox_mult,
                        "net_pnl_usd": result["net_pnl_usd"],
                        "baseline_net_pnl_usd": result["baseline_net_pnl_usd"],
                        "improvement_vs_fixed_baseline_usd": result["improvement_vs_fixed_baseline_usd"],
                        "fills": result["stats"]["fills"],
                        "filled_qty": result["stats"]["filled_qty"],
                        "final_inventory": result["final_inventory"],
                        "fees_usd": result["fees_usd"],
                        "quote_enabled": result["stats"]["quote_enabled"],
                        "toxicity_suppressed": result["stats"]["toxicity_suppressed"],
                    }
                )

        eligible = [row for row in selection if int(row["fills"]) >= MIN_INNER_FILLS]
        if not eligible:
            eligible = list(selection)

        selected = max(
            eligible,
            key=lambda row: (
                float(row["improvement_vs_fixed_baseline_usd"]),
                float(row["net_pnl_usd"]),
                -abs(float(row["final_inventory"])),
                -float(row["toxicity_multiplier"]),
                -float(row["min_edge_bps"]),
            ),
        )

        outer = replay_test_session(
            captures_root / test_session,
            test_session,
            models,
            half_spread_bps=2.5,
            min_edge_bps=float(selected["min_edge_bps"]),
            toxicity_multiplier=float(selected["toxicity_multiplier"]),
        )

        folds[test_session] = {
            "training_sessions": train_sessions,
            "training_sizes": sizes,
            "inner_validation_session": inner_session,
            "selected": selected,
            "inner_results": selection,
            "outer_test": {
                "min_edge_bps": float(selected["min_edge_bps"]),
                "toxicity_multiplier": float(selected["toxicity_multiplier"]),
                "net_pnl_usd": outer["net_pnl_usd"],
                "baseline_net_pnl_usd": outer["baseline_net_pnl_usd"],
                "improvement_vs_fixed_baseline_usd": outer["improvement_vs_fixed_baseline_usd"],
                "fills": outer["stats"]["fills"],
                "filled_qty": outer["stats"]["filled_qty"],
                "fees_usd": outer["fees_usd"],
                "final_inventory": outer["final_inventory"],
                "quote_enabled": outer["stats"]["quote_enabled"],
                "toxicity_suppressed": outer["stats"]["toxicity_suppressed"],
            },
        }

    return {
        "protocol": (
            "nested walk-forward: train on prior-session first halves; "
            "select toxicity/risk parameters on immediately prior-session second half; "
            "evaluate once on untouched outer-session second half"
        ),
        "fixed_half_spread_bps": 2.5,
        "min_edge_grid_bps": list(MIN_EDGE_GRID_BPS),
        "toxicity_multiplier_grid": list(TOXICITY_MULTIPLIER_GRID),
        "minimum_inner_fills": MIN_INNER_FILLS,
        "folds": folds,
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
