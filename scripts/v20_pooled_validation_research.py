"""Research-only pooled V20 validation across independent authentic sessions.

This script does not alter the production certification gate. It asks a stronger
question than per-session candidate selection: can one common parameter set,
selected only from the training halves of A/B/C/D together, generalize to all
untouched validation halves?

The candidate grid and event-replay mechanics are imported from the existing
V20 certification runner so this diagnostic uses the same fill/event model.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.v20_event_backtest_capture import load_events, load_snapshot
from scripts.v20_performance_certify import (
    MIN_TRAIN_FILLS_FOR_SELECTION,
    _candidate_grid,
    _load_config,
    _run,
    _score,
    _split_events,
    summarize,
)


SESSIONS = ("A", "B", "C", "D")


def _manifest(path: Path) -> dict[str, Any]:
    return json.loads((path / "manifest.json").read_text(encoding="utf-8"))


def _load_session(path: Path):
    manifest = _manifest(path)
    snapshot = load_snapshot(path)
    depth, trades, counts = load_events(path)
    train_snapshot, train_depth, train_trades, valid_snapshot, valid_depth, valid_trades = _split_events(
        snapshot, depth, trades
    )
    return {
        "manifest": manifest,
        "counts": counts,
        "train_snapshot": train_snapshot,
        "train_depth": train_depth,
        "train_trades": train_trades,
        "valid_snapshot": valid_snapshot,
        "valid_depth": valid_depth,
        "valid_trades": valid_trades,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--captures-root", type=Path, required=True)
    parser.add_argument("--baseline-config", type=Path, default=Path("app/mm/config_v20_eco_v1_actual_fees.json"))
    parser.add_argument("--candidate-config", type=Path, default=Path("app/mm/config_backtest_toxicity_v1.json"))
    parser.add_argument("--maker-fee-bps", type=float, default=1.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    sessions = {name: _load_session(args.captures_root / name) for name in SESSIONS}
    baseline = _load_config(args.baseline_config, args.maker_fee_bps)
    candidate_base = _load_config(args.candidate_config, args.maker_fee_bps)
    candidates = _candidate_grid(candidate_base)

    train_baselines: dict[str, Any] = {}
    for name, data in sessions.items():
        train_baselines[name] = _run(
            baseline,
            data["train_snapshot"],
            data["train_depth"],
            data["train_trades"],
        )

    records: list[dict[str, Any]] = []
    for candidate in candidates:
        per_session: dict[str, Any] = {}
        eligible = True
        aggregate_objective = 0.0
        aggregate_fills = 0
        aggregate_pnl = 0.0
        for name, data in sessions.items():
            result = _run(
                candidate,
                data["train_snapshot"],
                data["train_depth"],
                data["train_trades"],
            )
            objective, fills = _score(result)
            per_session[name] = {
                "fills": fills,
                "net_pnl_usd": result.net_pnl_usd,
                "avg_adverse_selection_bps": result.avg_adverse_selection_bps,
                "objective": objective,
            }
            eligible = eligible and fills >= MIN_TRAIN_FILLS_FOR_SELECTION
            aggregate_objective += objective
            aggregate_fills += fills
            aggregate_pnl += result.net_pnl_usd

        records.append(
            {
                "config": candidate,
                "eligible_all_sessions": eligible,
                "aggregate_objective": aggregate_objective,
                "aggregate_fills": aggregate_fills,
                "aggregate_train_pnl_usd": aggregate_pnl,
                "per_session": per_session,
            }
        )

    eligible = [r for r in records if r["eligible_all_sessions"]]
    if not eligible:
        raise SystemExit("POOLED_RESEARCH_BLOCKED: no common candidate meets minimum training fills in all four sessions")

    selected_record = max(
        eligible,
        key=lambda r: (float(r["aggregate_objective"]), int(r["aggregate_fills"])),
    )
    selected = selected_record["config"]

    validation: dict[str, Any] = {}
    aggregate_candidate_pnl = 0.0
    aggregate_baseline_pnl = 0.0
    positive_sessions = 0
    beats_baseline_sessions = 0
    candidate_fill_sessions = 0

    for name, data in sessions.items():
        candidate_result = _run(
            selected,
            data["valid_snapshot"],
            data["valid_depth"],
            data["valid_trades"],
        )
        baseline_result = _run(
            baseline,
            data["valid_snapshot"],
            data["valid_depth"],
            data["valid_trades"],
        )
        improvement = candidate_result.net_pnl_usd - baseline_result.net_pnl_usd
        aggregate_candidate_pnl += candidate_result.net_pnl_usd
        aggregate_baseline_pnl += baseline_result.net_pnl_usd
        positive_sessions += int(candidate_result.net_pnl_usd > 0)
        beats_baseline_sessions += int(improvement > 0)
        candidate_fill_sessions += int(candidate_result.fills >= 100)
        validation[name] = {
            "selected_candidate": summarize(candidate_result),
            "baseline": summarize(baseline_result),
            "net_pnl_improvement_usd": improvement,
        }

    pooled_improvement = aggregate_candidate_pnl - aggregate_baseline_pnl
    research_gates = {
        "common_candidate_selected_from_training_only": True,
        "aggregate_validation_net_pnl_positive": aggregate_candidate_pnl > 0,
        "aggregate_validation_beats_baseline": pooled_improvement > 0,
        "at_least_3_of_4_sessions_positive_pnl": positive_sessions >= 3,
        "at_least_3_of_4_sessions_beat_baseline": beats_baseline_sessions >= 3,
        "at_least_3_of_4_sessions_have_100_candidate_fills": candidate_fill_sessions >= 3,
    }

    report = {
        "research_status": "POOLED_PASS" if all(research_gates.values()) else "POOLED_FAIL",
        "scope": "research_only_not_certification",
        "source": {
            "sessions": list(SESSIONS),
            "maker_fee_bps": args.maker_fee_bps,
            "candidate_grid_size": len(candidates),
            "eligible_common_candidates": len(eligible),
            "minimum_training_fills_per_session": MIN_TRAIN_FILLS_FOR_SELECTION,
        },
        "selected_common_candidate": {
            "base_half_spread_bps": selected.base_half_spread_bps,
            "inventory_penalty_bps": selected.inventory_penalty_bps,
            "toxicity_imbalance_threshold": selected.toxicity_imbalance_threshold,
            "toxicity_flow_threshold": selected.toxicity_flow_threshold,
            "microprice_skew_bps": selected.microprice_skew_bps,
        },
        "training": {
            "aggregate_pnl_usd": selected_record["aggregate_train_pnl_usd"],
            "aggregate_fills": selected_record["aggregate_fills"],
            "per_session": selected_record["per_session"],
            "baseline_per_session": {
                name: summarize(result) for name, result in train_baselines.items()
            },
        },
        "validation": {
            "aggregate_candidate_pnl_usd": aggregate_candidate_pnl,
            "aggregate_baseline_pnl_usd": aggregate_baseline_pnl,
            "aggregate_improvement_usd": pooled_improvement,
            "positive_sessions": positive_sessions,
            "beats_baseline_sessions": beats_baseline_sessions,
            "sessions_with_100_candidate_fills": candidate_fill_sessions,
            "per_session": validation,
        },
        "research_gates": research_gates,
        "top_common_training_candidates": [
            {
                "aggregate_objective": r["aggregate_objective"],
                "aggregate_train_pnl_usd": r["aggregate_train_pnl_usd"],
                "aggregate_fills": r["aggregate_fills"],
                "eligible_all_sessions": r["eligible_all_sessions"],
                "config": {
                    "base_half_spread_bps": r["config"].base_half_spread_bps,
                    "inventory_penalty_bps": r["config"].inventory_penalty_bps,
                    "toxicity_imbalance_threshold": r["config"].toxicity_imbalance_threshold,
                    "toxicity_flow_threshold": r["config"].toxicity_flow_threshold,
                    "microprice_skew_bps": r["config"].microprice_skew_bps,
                },
            }
            for r in sorted(
                eligible,
                key=lambda x: (x["aggregate_objective"], x["aggregate_fills"]),
                reverse=True,
            )[:10]
        ],
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["research_status"] == "POOLED_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
