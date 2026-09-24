"""Sweep directional_flow_threshold across 0.3, 0.5, 0.7, 0.9.

Each run uses the same five captures, authenticated fees, inventory
suppression, and existing toxicity filter.  Only the threshold varies.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.mm.config import V20Config
from app.mm.event_backtest import run_event_backtest
from scripts.v20_event_backtest_capture import load_snapshot, load_events

BASELINE_CONFIG = "app/mm/config_v20_eco_v1_actual_fees.json"
CAPTURE_IDS = ["3b8eee35", "477cf6ae", "9863cf18", "e4153485", "ebe81a64"]
THRESHOLDS = [0.3, 0.5, 0.7, 0.9]
OUT = Path("data/mm_directional_flow_sweep.json")


def clean(v):
    import math
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def run_capture(capture_id, config):
    matches = sorted(Path("data/captures").glob(f"{capture_id}*"))
    if not matches:
        raise FileNotFoundError(f"capture not found: {capture_id}")
    snapshot = load_snapshot(matches[0])
    depth, trades, _ = load_events(matches[0])
    result = run_event_backtest(snapshot, depth, trades, config)
    return {
        "fills": result.fills,
        "realized_pnl_usd": clean(result.realized_pnl_usd),
        "net_pnl_usd": clean(result.net_pnl_usd),
        "fees_usd": clean(result.fees_usd),
        "inventory_carry_usd": clean(result.inventory_carry_usd),
        "gross_spread_capture_usd": clean(result.gross_spread_capture_usd),
        "inventory_max": clean(result.inventory_max),
        "inventory_limit_breaches": result.inventory_limit_breaches,
        "directional_flow_suppressed_quotes": result.directional_flow_suppressed_quotes,
        "directional_flow_imbalance_mean": clean(result.directional_flow_imbalance_mean),
    }


def main():
    baseline, _ = V20Config.load_authoritative(BASELINE_CONFIG)
    captures_root = Path("data/captures")

    # Baseline
    baseline_results = {}
    for cid in CAPTURE_IDS:
        baseline_results[cid] = run_capture(cid, baseline)

    sweep_results = {}
    for threshold in THRESHOLDS:
        # Build candidate config from baseline + directional flow
        config_dict = {
            "symbol": baseline.symbol,
            "quote_interval_ms": baseline.quote_interval_ms,
            "base_half_spread_bps": baseline.base_half_spread_bps,
            "max_half_spread_bps": baseline.max_half_spread_bps,
            "inventory_target": baseline.inventory_target,
            "inventory_penalty_bps": baseline.inventory_penalty_bps,
            "max_position_notional_usd": baseline.max_position_notional_usd,
            "quote_size_usd": baseline.quote_size_usd,
            "toxicity_filter_enabled": baseline.toxicity_filter_enabled,
            "cancel_on_adverse_selection": baseline.cancel_on_adverse_selection,
            "adverse_selection_threshold_bps": baseline.adverse_selection_threshold_bps,
            "min_top_level_qty": baseline.min_top_level_qty,
            "inventory_suppression_enabled": True,
            "inventory_suppression_power": 1.0,
            "directional_flow_enabled": True,
            "directional_flow_threshold": threshold,
            "maker_fee_bps": baseline.maker_fee_bps,
            "maker_rebate_bps": baseline.maker_rebate_bps,
            "taker_fee_bps": baseline.taker_fee_bps,
            "live_order_submission": False,
        }
        config = V20Config(**config_dict)

        print(f"\n=== threshold={threshold} ===", flush=True)
        results = {}
        for cid in CAPTURE_IDS:
            results[cid] = run_capture(cid, config)
            r = results[cid]
            b = baseline_results[cid]
            print(
                f"  {cid}: fills={r['fills']:4d} realized={r['realized_pnl_usd']:>10.2f} "
                f"delta={r['realized_pnl_usd']-b['realized_pnl_usd']:>10.2f} "
                f"carry={r['inventory_carry_usd']:>10.2f} "
                f"suppressed={r['directional_flow_suppressed_quotes']}",
                flush=True,
            )

        total_realized = sum(r["realized_pnl_usd"] for r in results.values())
        total_fills = sum(r["fills"] for r in results.values())
        total_suppressed = sum(r["directional_flow_suppressed_quotes"] for r in results.values())
        max_inv = max(r["inventory_max"] for r in results.values())
        breaches = sum(r["inventory_limit_breaches"] for r in results.values())
        pos_captures = sum(1 for r in results.values() if r["realized_pnl_usd"] > 0)

        print(
            f"  TOTAL: fills={total_fills} realized={total_realized:.2f} "
            f"suppressed={total_suppressed} max_inv={max_inv:.2f} "
            f"breaches={breaches} positive_captures={pos_captures}/5",
            flush=True,
        )

        sweep_results[str(threshold)] = {
            "captures": results,
            "total_realized_pnl_usd": round(total_realized, 6),
            "total_fills": total_fills,
            "total_directional_flow_suppressed_quotes": total_suppressed,
            "max_inventory_usd": round(max_inv, 6),
            "total_inventory_limit_breaches": breaches,
            "positive_captures": pos_captures,
        }

    envelope = {
        "run_id": "V20-DIRECTIONAL-FLOW-SWEEP",
        "baseline_config": BASELINE_CONFIG,
        "same_captures": CAPTURE_IDS,
        "live_order_submission": False,
        "fill_model": "event_driven",
        "baseline": {cid: {k: v for k, v in baseline_results[cid].items()} for cid in CAPTURE_IDS},
        "sweep": sweep_results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(envelope, indent=2) + "\n")
    print(json.dumps(envelope, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())