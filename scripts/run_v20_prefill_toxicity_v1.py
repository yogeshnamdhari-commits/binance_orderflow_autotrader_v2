"""V20 isolated pre-fill toxicity experiment.

Compares the frozen V20 baseline, which uses the existing deterministic
book/flow threshold filter, with a candidate that disables that threshold
rule and instead uses an online causal Bayesian estimate of:

    P(adverse | side, book-imbalance bucket, flow-imbalance bucket)

Only labels from prior completed fills are admitted to the estimator. The
same five captures, authenticated fees, hard inventory cap, quote engine,
and inventory policy are otherwise held fixed.

This is an experiment report, not a certification gate.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.mm.config import V20Config
from app.mm.event_backtest import run_event_backtest
from scripts.v20_event_backtest_capture import load_snapshot, load_events

BASELINE_CONFIG = "app/mm/config_v20_eco_v1_actual_fees.json"
CANDIDATE_CONFIG = "app/mm/config_v20_prefill_toxicity_v1.json"
OUT = Path("data/mm_prefill_toxicity_v1_comparison.json")

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
            "existing_toxicity_suppressed_quotes": result.toxicity_suppressed_quotes,
            "prefill_toxicity_suppressed_quotes": result.prefill_toxicity_suppressed_quotes,
            "prefill_toxicity_bid_suppressed": result.prefill_toxicity_bid_suppressed,
            "prefill_toxicity_ask_suppressed": result.prefill_toxicity_ask_suppressed,
            "prefill_toxicity_model_observations": result.prefill_toxicity_model_observations,
            "prefill_toxicity_probability_mean": clean(result.prefill_toxicity_probability_mean),
            "prefill_toxicity_probability_max": clean(result.prefill_toxicity_probability_max),
            "gate_pass": passed,
            "gate_reasons": reasons if reasons else ["pass"],
            "runtime_seconds": round(elapsed, 3),
        }
    return output


def aggregate(results: dict) -> dict:
    return {
        "captures": len(results),
        "total_fills": sum(x["fills"] for x in results.values()),
        "total_realized_pnl_usd": round(
            sum(x["realized_pnl_usd"] for x in results.values()), 6
        ),
        "total_net_pnl_usd": round(
            sum(x["net_pnl_usd"] for x in results.values()), 6
        ),
        "total_fees_usd": round(sum(x["fees_usd"] for x in results.values()), 6),
        "total_inventory_carry_usd": round(
            sum(x["inventory_carry_usd"] for x in results.values()), 6
        ),
        "max_inventory_usd": round(
            max(x["inventory_max"] for x in results.values()), 6
        ),
        "total_inventory_limit_breaches": sum(
            x["inventory_limit_breaches"] for x in results.values()
        ),
        "captures_pass": sum(1 for x in results.values() if x["gate_pass"]),
        "total_prefill_suppressed_quotes": sum(
            x["prefill_toxicity_suppressed_quotes"] for x in results.values()
        ),
        "total_prefill_model_observations": sum(
            x["prefill_toxicity_model_observations"] for x in results.values()
        ),
    }


def main() -> int:
    baseline, baseline_sha = V20Config.load_authoritative(BASELINE_CONFIG)
    candidate, candidate_sha = V20Config.load_authoritative(CANDIDATE_CONFIG)

    if baseline.live_order_submission or candidate.live_order_submission:
        raise RuntimeError("live_order_submission must remain false")

    shared = {
        "symbol": (baseline.symbol, candidate.symbol),
        "quote_interval_ms": (baseline.quote_interval_ms, candidate.quote_interval_ms),
        "base_half_spread_bps": (baseline.base_half_spread_bps, candidate.base_half_spread_bps),
        "max_half_spread_bps": (baseline.max_half_spread_bps, candidate.max_half_spread_bps),
        "inventory_target": (baseline.inventory_target, candidate.inventory_target),
        "inventory_penalty_bps": (baseline.inventory_penalty_bps, candidate.inventory_penalty_bps),
        "max_position_notional_usd": (
            baseline.max_position_notional_usd,
            candidate.max_position_notional_usd,
        ),
        "quote_size_usd": (baseline.quote_size_usd, candidate.quote_size_usd),
        "maker_fee_bps": (baseline.maker_fee_bps, candidate.maker_fee_bps),
        "maker_rebate_bps": (baseline.maker_rebate_bps, candidate.maker_rebate_bps),
        "taker_fee_bps": (baseline.taker_fee_bps, candidate.taker_fee_bps),
        "inventory_suppression_enabled": (
            baseline.inventory_suppression_enabled,
            candidate.inventory_suppression_enabled,
        ),
    }
    mismatches = {key: values for key, values in shared.items() if values[0] != values[1]}
    if mismatches:
        raise RuntimeError(f"isolated-experiment invariant violated: {mismatches}")

    if not baseline.toxicity_filter_enabled:
        raise RuntimeError("baseline must keep the frozen existing toxicity filter enabled")
    if candidate.toxicity_filter_enabled:
        raise RuntimeError("candidate must disable the existing threshold toxicity filter")
    if not candidate.prefill_toxicity_filter_enabled:
        raise RuntimeError("candidate pre-fill toxicity filter is not enabled")
    if baseline.prefill_toxicity_filter_enabled:
        raise RuntimeError("baseline pre-fill toxicity filter must be disabled")

    captures_root = Path("data/captures")
    baseline_results = run_arm("baseline", baseline, captures_root)
    candidate_results = run_arm("prefill_toxicity_v1", candidate, captures_root)

    comparison: dict = {}
    for capture in CAPTURE_IDS:
        b_key = next(k for k in baseline_results if k.startswith(capture))
        c_key = next(k for k in candidate_results if k.startswith(capture))
        b = baseline_results[b_key]
        c = candidate_results[c_key]
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
            "baseline_avg_adverse_selection_bps": b["avg_adverse_selection_bps"],
            "candidate_avg_adverse_selection_bps": c["avg_adverse_selection_bps"],
            "baseline_toxicity_suppressed_quotes": b["existing_toxicity_suppressed_quotes"],
            "candidate_prefill_suppressed_quotes": c["prefill_toxicity_suppressed_quotes"],
            "candidate_model_observations": c["prefill_toxicity_model_observations"],
            "candidate_probability_mean": c["prefill_toxicity_probability_mean"],
            "candidate_probability_max": c["prefill_toxicity_probability_max"],
        }

    envelope = {
        "run_id": "V20-PREFILL-TOXICITY-V1",
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
            "Replacing the existing deterministic threshold toxicity rule with "
            "a causal online Bayesian estimate of P(adverse | side, book-imbalance "
            "bucket, flow-imbalance bucket), suppressing a side when posterior "
            "probability reaches 0.50 after at least 10 prior labeled observations, "
            "reduces adverse selection and/or inventory carry without changing "
            "fees, spread, inventory cap, or the underlying quote signal."
        ),
        "label_definition": (
            "A fill is adverse when the first observed mid at or after the "
            "configured horizon moves against the filled side by at least "
            "adverse_selection_threshold_bps."
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
