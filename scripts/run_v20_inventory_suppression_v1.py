"""V20 isolated inventory-suppression experiment.

Compares the frozen V20 baseline against one deterministic candidate:
continuous reduction of the inventory-increasing quote side as signed
inventory_ratio approaches the hard $5,000 notional limit.

The same five captures, authenticated fees, existing toxicity filter,
event-driven fill model, and hard inventory cap are used in both arms.
This runner is an experiment report, not a certification gate.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import time
from pathlib import Path

from dataclasses import replace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.mm.config import V20Config
from app.mm.event_backtest import run_event_backtest
from scripts.v20_event_backtest_capture import load_snapshot, load_events

BASELINE_CONFIG = "app/mm/config_v20_eco_v1_actual_fees.json"
CANDIDATE_CONFIG = "app/mm/config_v20_inventory_suppression_v1.json"
OUT = Path("data/mm_inventory_suppression_v1_comparison.json")

CAPTURE_IDS = [
    "3b8eee35",
    "477cf6ae",
    "9863cf18",
    "e4153485",
    "ebe81a64",
]


def clean(value: float) -> float | None:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def gate_status(result, config) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if result.fills <= 0:
        reasons.append("insufficient_fills")
    if result.realized_pnl_usd <= 0:
        reasons.append("realized_pnl_not_positive")
    if result.net_pnl_usd <= 0:
        reasons.append("net_pnl_not_positive")
    if result.inventory_max > config.max_position_notional_usd + 1e-6:
        reasons.append("inventory_exceeds_limit")
    if result.inventory_limit_breaches > 0:
        reasons.append("inventory_limit_breached")
    return not reasons, reasons


def run_arm(name: str, config: V20Config, captures_root: Path) -> dict:
    output: dict = {}
    for capture_id in CAPTURE_IDS:
        matches = sorted(captures_root.glob(f"{capture_id}*"))
        if not matches:
            raise FileNotFoundError(f"capture not found: {capture_id}")
        capture_dir = matches[0]
        snapshot = load_snapshot(capture_dir)
        depth, trades, _counts = load_events(capture_dir)

        started = time.time()
        result = run_event_backtest(snapshot, depth, trades, config)
        elapsed = time.time() - started
        passed, reasons = gate_status(result, config)

        if abs(result.attribution_residual_usd) > 1e-6:
            raise RuntimeError(
                f"{name}/{capture_id}: attribution residual "
                f"{result.attribution_residual_usd} is not reconciled"
            )
        if result.inventory_max > config.max_position_notional_usd + 1e-6:
            raise RuntimeError(
                f"{name}/{capture_id}: hard inventory limit exceeded "
                f"{result.inventory_max:.6f} > {config.max_position_notional_usd:.6f}"
            )

        output[capture_dir.name] = {
            "fills": result.fills,
            "realized_pnl_usd": clean(result.realized_pnl_usd),
            "net_pnl_usd": clean(result.net_pnl_usd),
            "fees_usd": clean(result.fees_usd),
            "gross_spread_capture_usd": clean(result.gross_spread_capture_usd),
            "inventory_carry_usd": clean(result.inventory_carry_usd),
            "inventory_mtm_usd": clean(result.inventory_mtm_usd),
            "adverse_selection_usd": clean(result.adverse_selection_usd),
            "attribution_residual_usd": clean(result.attribution_residual_usd),
            "inventory_max": clean(result.inventory_max),
            "inventory_final": clean(result.final_inventory),
            "inventory_limit_breaches": result.inventory_limit_breaches,
            "avg_adverse_selection_bps": clean(result.avg_adverse_selection_bps),
            "inventory_suppression_events": result.inventory_suppression_events,
            "inventory_suppressed_bid_qty": clean(result.inventory_suppressed_bid_qty),
            "inventory_suppressed_ask_qty": clean(result.inventory_suppressed_ask_qty),
            "inventory_ratio_abs_mean": clean(result.inventory_ratio_abs_mean),
            "inventory_ratio_abs_max": clean(result.inventory_ratio_abs_max),
            "gate_pass": passed,
            "gate_reasons": reasons if reasons else ["pass"],
            "runtime_seconds": round(elapsed, 3),
        }
    return output


def aggregate(results: dict) -> dict:
    total_fills = sum(x["fills"] for x in results.values())
    totals = {
        "captures": len(results),
        "total_fills": total_fills,
        "total_realized_pnl_usd": round(
            sum(x["realized_pnl_usd"] for x in results.values()), 6
        ),
        "total_net_pnl_usd": round(
            sum(x["net_pnl_usd"] for x in results.values()), 6
        ),
        "total_fees_usd": round(
            sum(x["fees_usd"] for x in results.values()), 6
        ),
        "total_inventory_carry_usd": round(
            sum(x["inventory_carry_usd"] for x in results.values()), 6
        ),
        "total_gross_spread_capture_usd": round(
            sum(x["gross_spread_capture_usd"] for x in results.values()), 6
        ),
        "max_inventory_usd": round(
            max(x["inventory_max"] for x in results.values()), 6
        ),
        "total_inventory_limit_breaches": sum(
            x["inventory_limit_breaches"] for x in results.values()
        ),
        "captures_pass": sum(1 for x in results.values() if x["gate_pass"]),
    }
    if results:
        weights = [max(1, x["fills"]) for x in results.values()]
        totals["fill_weighted_abs_inventory_ratio"] = round(
            sum(
                x["inventory_ratio_abs_mean"] * w
                for x, w in zip(results.values(), weights)
            ) / sum(weights),
            6,
        )
        totals["total_inventory_suppression_events"] = sum(
            x["inventory_suppression_events"] for x in results.values()
        )
    return totals


def main() -> int:
    baseline, baseline_sha = V20Config.load_authoritative(BASELINE_CONFIG)
    candidate, candidate_sha = V20Config.load_authoritative(CANDIDATE_CONFIG)

    if baseline.live_order_submission or candidate.live_order_submission:
        raise RuntimeError("live_order_submission must remain false")

    # Confirm the experiment changes only the intended mechanism.
    checks = {
        "symbol": (baseline.symbol, candidate.symbol),
        "quote_interval_ms": (baseline.quote_interval_ms, candidate.quote_interval_ms),
        "base_half_spread_bps": (baseline.base_half_spread_bps, candidate.base_half_spread_bps),
        "max_half_spread_bps": (baseline.max_half_spread_bps, candidate.max_half_spread_bps),
        "inventory_penalty_bps": (baseline.inventory_penalty_bps, candidate.inventory_penalty_bps),
        "max_position_notional_usd": (
            baseline.max_position_notional_usd,
            candidate.max_position_notional_usd,
        ),
        "maker_fee_bps": (baseline.maker_fee_bps, candidate.maker_fee_bps),
        "maker_rebate_bps": (baseline.maker_rebate_bps, candidate.maker_rebate_bps),
        "taker_fee_bps": (baseline.taker_fee_bps, candidate.taker_fee_bps),
        "toxicity_filter_enabled": (
            baseline.toxicity_filter_enabled,
            candidate.toxicity_filter_enabled,
        ),
    }
    mismatches = {
        key: values for key, values in checks.items() if values[0] != values[1]
    }
    if mismatches:
        raise RuntimeError(f"isolated-experiment invariant violated: {mismatches}")

    if baseline.inventory_suppression_enabled:
        raise RuntimeError("baseline must have inventory_suppression_enabled=false")
    if not candidate.inventory_suppression_enabled:
        raise RuntimeError("candidate must have inventory_suppression_enabled=true")
    if abs(candidate.inventory_suppression_power - 1.0) > 1e-12:
        raise RuntimeError("candidate inventory_suppression_power must remain the frozen 1.0")

    captures_root = Path("data/captures")
    baseline_results = run_arm("baseline", baseline, captures_root)
    candidate_results = run_arm("inventory_suppression_v1", candidate, captures_root)

    comparison: dict = {}
    for capture in CAPTURE_IDS:
        b = baseline_results[next(k for k in baseline_results if k.startswith(capture))]
        c = candidate_results[next(k for k in candidate_results if k.startswith(capture))]
        comparison[capture] = {
            "delta_realized_pnl_usd": round(c["realized_pnl_usd"] - b["realized_pnl_usd"], 6),
            "delta_net_pnl_usd": round(c["net_pnl_usd"] - b["net_pnl_usd"], 6),
            "delta_inventory_carry_usd": round(
                c["inventory_carry_usd"] - b["inventory_carry_usd"], 6
            ),
            "delta_fees_usd": round(c["fees_usd"] - b["fees_usd"], 6),
            "delta_fills": c["fills"] - b["fills"],
            "baseline_realized_pnl_usd": b["realized_pnl_usd"],
            "candidate_realized_pnl_usd": c["realized_pnl_usd"],
            "baseline_inventory_max": b["inventory_max"],
            "candidate_inventory_max": c["inventory_max"],
            "candidate_suppression_events": c["inventory_suppression_events"],
        }

    envelope = {
        "run_id": "V20-INVENTORY-SUPPRESSION-V1",
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
        ).decode().strip(),
        "baseline_config": BASELINE_CONFIG,
        "baseline_config_sha256": baseline_sha,
        "candidate_config": CANDIDATE_CONFIG,
        "candidate_config_sha256": candidate_sha,
        "same_captures": CAPTURE_IDS,
        "live_order_submission": False,
        "fill_model": "event_driven",
        "hypothesis": (
            "Continuously reducing only the inventory-increasing quote size "
            "as signed inventory_ratio approaches ±1 will reduce inventory "
            "carry without changing the baseline signal, fees, spread, "
            "toxicity filter, or hard inventory cap."
        ),
        "baseline": aggregate(baseline_results),
        "candidate": aggregate(candidate_results),
        "comparison": comparison,
        "results": {
            "baseline": baseline_results,
            "candidate": candidate_results,
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(envelope, indent=2) + "\n")
    print(json.dumps(envelope, indent=2))

    # Experiment completed successfully. Candidate certification is deliberately
    # NOT encoded as process success; economic viability must be judged from the
    # frozen comparison report and subsequent OOS testing.
    return 0


if __name__ == "__main__":
    sys.exit(main())
