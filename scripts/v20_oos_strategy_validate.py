"""Out-of-sample strategy validator for frozen V20 candidate configs.

Research-only. Requires no Binance credentials. Consumes already-sealed local
captures and never modifies candidate parameters.

Two modes:

  retrospective  Existing captures used during candidate selection. Labelled
                explicitly as RETROSPECTIVE / in-sample evidence. Never treated
                as true OOS.

  oos           A capture collected AFTER the candidate config was frozen.
                The candidate fingerprint is recorded before the capture is
                evaluated, and the strategy is evaluated exactly once.

The validator is deliberately parameter-free: it accepts a frozen candidate
config file and a capture directory, and reports per-capture and aggregate
metrics without re-tuning anything.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.mm.config import V20Config, config_sha256
from app.mm.event_backtest import run_event_backtest
from scripts.v20_event_backtest_capture import load_snapshot, load_events


def clean(value: float) -> float | None:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def evaluate_capture(config: V20Config, capture_dir: Path) -> dict:
    snapshot = load_snapshot(capture_dir)
    depth, trades, _counts = load_events(capture_dir)

    result = run_event_backtest(snapshot, depth, trades, config)

    if abs(result.attribution_residual_usd) > 1e-6:
        raise RuntimeError(
            f"{capture_dir.name}: attribution residual "
            f"{result.attribution_residual_usd} is not reconciled"
        )

    return {
        "capture_dir": capture_dir.name,
        "fills": result.fills,
        "gross_spread_capture_usd": clean(result.gross_spread_capture_usd),
        "fees_usd": clean(result.fees_usd),
        "realized_pnl_usd": clean(result.realized_pnl_usd),
        "net_pnl_usd": clean(result.net_pnl_usd),
        "inventory_carry_usd": clean(result.inventory_carry_usd),
        "inventory_mtm_usd": clean(result.inventory_mtm_usd),
        "adverse_selection_usd": clean(result.adverse_selection_usd),
        "inventory_max": clean(result.inventory_max),
        "inventory_final": clean(result.final_inventory),
        "inventory_limit_breaches": result.inventory_limit_breaches,
        "pnl_per_fill": (
            round(result.realized_pnl_usd / result.fills, 6)
            if result.fills > 0
            else None
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, help="frozen candidate config JSON")
    parser.add_argument("--captures", nargs="+", required=True, help="capture directories")
    parser.add_argument("--label", default="OOS", help="retrospective or oos")
    parser.add_argument("--out", default=None, help="output JSON path")
    args = parser.parse_args()

    candidate, candidate_sha = V20Config.load_authoritative(args.candidate)
    if candidate.live_order_submission:
        raise RuntimeError("candidate must have live_order_submission=false")

    captures_root = Path("data/captures")
    per_capture: dict = {}
    for capture_id in args.captures:
        matches = sorted(captures_root.glob(f"{capture_id}*"))
        if not matches:
            raise FileNotFoundError(f"capture not found: {capture_id}")
        per_capture[matches[0].name] = evaluate_capture(candidate, matches[0])

    fills = sum(x["fills"] for x in per_capture.values())
    gross = sum(x["gross_spread_capture_usd"] or 0.0 for x in per_capture.values())
    fees = sum(x["fees_usd"] or 0.0 for x in per_capture.values())
    realized = sum(x["realized_pnl_usd"] or 0.0 for x in per_capture.values())
    net = sum(x["net_pnl_usd"] or 0.0 for x in per_capture.values())
    carry = sum(x["inventory_carry_usd"] or 0.0 for x in per_capture.values())
    max_inv = max(x["inventory_max"] or 0.0 for x in per_capture.values())
    breaches = sum(x["inventory_limit_breaches"] for x in per_capture.values())
    positive = sum(1 for x in per_capture.values() if (x["realized_pnl_usd"] or 0.0) > 0)

    worst = min(per_capture.values(), key=lambda x: x["realized_pnl_usd"] or float("inf"))
    best = max(per_capture.values(), key=lambda x: x["realized_pnl_usd"] or float("-inf"))

    report = {
        "label": args.label,
        "candidate_config": args.candidate,
        "candidate_config_sha256": candidate_sha,
        "candidate_fingerprint": candidate.canonical_dict(),
        "captures_evaluated": len(per_capture),
        "aggregate": {
            "total_fills": fills,
            "total_gross_spread_capture_usd": round(gross, 6),
            "total_fees_usd": round(fees, 6),
            "total_realized_pnl_usd": round(realized, 6),
            "total_net_pnl_usd": round(net, 6),
            "total_inventory_carry_usd": round(carry, 6),
            "max_inventory_usd": round(max_inv, 6),
            "total_inventory_limit_breaches": breaches,
            "captures_positive_realized": positive,
            "pnl_per_fill": round(realized / fills, 6) if fills > 0 else None,
        },
        "per_capture": per_capture,
        "worst_capture": {
            "capture_dir": worst["capture_dir"],
            "realized_pnl_usd": worst["realized_pnl_usd"],
        },
        "best_capture": {
            "capture_dir": best["capture_dir"],
            "realized_pnl_usd": best["realized_pnl_usd"],
        },
    }

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=2) + "\n")

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())