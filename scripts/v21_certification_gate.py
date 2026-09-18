"""Research-only economic certification gate for V21.

The gate never enables live trading. It fails closed unless the selected nested
walk-forward configuration demonstrates positive aggregate OOS economics and
a positive improvement over the fixed V20 event-replay baseline.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


MIN_TOTAL_OOS_FILLS = 10
MIN_OOS_FOLDS = 2
MIN_FILLS_PER_OOS_FOLD = 10


def evaluate(
    learned_path: Path,
    risk_sweep_path: Path,
) -> dict[str, Any]:
    learned = json.loads(learned_path.read_text(encoding="utf-8"))
    sweep = json.loads(risk_sweep_path.read_text(encoding="utf-8"))

    folds = sweep.get("folds", {})
    outer = []
    for session, fold in folds.items():
        result = fold.get("outer_test", {})
        outer.append(
            {
                "session": session,
                "net_pnl_usd": float(result.get("net_pnl_usd", 0.0)),
                "baseline_net_pnl_usd": float(result.get("baseline_net_pnl_usd", 0.0)),
                "improvement_vs_fixed_baseline_usd": float(
                    result.get("improvement_vs_fixed_baseline_usd", 0.0)
                ),
                "fills": int(result.get("fills", 0)),
                "final_inventory": float(result.get("final_inventory", 0.0)),
            }
        )

    aggregate_net_pnl = sum(row["net_pnl_usd"] for row in outer)
    aggregate_baseline = sum(row["baseline_net_pnl_usd"] for row in outer)
    aggregate_improvement = sum(
        row["improvement_vs_fixed_baseline_usd"] for row in outer
    )
    total_fills = sum(row["fills"] for row in outer)

    checks = {
        "minimum_outer_oos_folds": len(outer) >= MIN_OOS_FOLDS,
        "aggregate_net_pnl_positive": aggregate_net_pnl > 0.0,
        "aggregate_improvement_positive": aggregate_improvement > 0.0,
        "minimum_total_oos_fills": total_fills >= MIN_TOTAL_OOS_FILLS,
        "every_outer_fold_profitable": bool(outer) and all(
            row["net_pnl_usd"] > 0.0 for row in outer
        ),
        "every_outer_fold_beats_fixed_baseline": bool(outer) and all(
            row["improvement_vs_fixed_baseline_usd"] > 0.0 for row in outer
        ),
        "every_outer_fold_has_minimum_fills": bool(outer) and all(
            row["fills"] >= MIN_FILLS_PER_OOS_FOLD for row in outer
        ),
        "live_submission_disabled": False,
    }

    # Keep the control explicit and inspectable in the report.
    config = learned.get("config", {})
    checks["live_submission_disabled"] = not bool(
        config.get("live_order_submission", False)
    )

    certified = all(checks.values())
    return {
        "status": "CERTIFIED" if certified else "NOT_CERTIFIED",
        "protocol": "nested walk-forward economic gate",
        "outer_folds": outer,
        "aggregate": {
            "net_pnl_usd": aggregate_net_pnl,
            "baseline_net_pnl_usd": aggregate_baseline,
            "improvement_vs_fixed_baseline_usd": aggregate_improvement,
            "total_fills": total_fills,
        },
        "checks": checks,
        "reason": (
            "All economic and safety checks passed."
            if certified
            else "At least one certification gate failed; live deployment remains blocked."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--learned", type=Path, required=True)
    parser.add_argument("--risk-sweep", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = evaluate(args.learned, args.risk_sweep)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))

    return 0 if report["status"] == "CERTIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
