"""Run directional flow at threshold 0.7 only."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.mm.config import V20Config
from app.mm.event_backtest import run_event_backtest
from scripts.v20_event_backtest_capture import load_snapshot, load_events

BASELINE_CONFIG = "app/mm/config_v20_eco_v1_actual_fees.json"
CAPTURE_IDS = ["3b8eee35", "477cf6ae", "9863cf18", "e4153485", "ebe81a64"]
THRESHOLD = 0.7


def run_capture(capture_id, config):
    matches = sorted(Path("data/captures").glob(f"{capture_id}*"))
    snapshot = load_snapshot(matches[0])
    depth, trades, _ = load_events(matches[0])
    return run_event_backtest(snapshot, depth, trades, config)


def main():
    baseline, _ = V20Config.load_authoritative(BASELINE_CONFIG)

    baseline_results = {}
    for cid in CAPTURE_IDS:
        baseline_results[cid] = run_capture(cid, baseline)

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
        "directional_flow_threshold": THRESHOLD,
        "maker_fee_bps": baseline.maker_fee_bps,
        "maker_rebate_bps": baseline.maker_rebate_bps,
        "taker_fee_bps": baseline.taker_fee_bps,
        "live_order_submission": False,
    }
    config = V20Config(**config_dict)

    print(f"threshold={THRESHOLD}", flush=True)
    cap_results = {}
    for cid in CAPTURE_IDS:
        r = run_capture(cid, config)
        b = baseline_results[cid]
        cap_results[cid] = {
            "fills": r.fills,
            "realized_pnl_usd": r.realized_pnl_usd,
            "delta": r.realized_pnl_usd - b.realized_pnl_usd,
            "inventory_carry_usd": r.inventory_carry_usd,
            "inventory_max": r.inventory_max,
            "suppressed": r.directional_flow_suppressed_quotes,
        }
        print(
            f"  {cid}: fills={r.fills} realized={r.realized_pnl_usd:.2f} "
            f"delta={r.realized_pnl_usd - b.realized_pnl_usd:.2f} "
            f"carry={r.inventory_carry_usd:.2f} "
            f"suppressed={r.directional_flow_suppressed_quotes}",
            flush=True,
        )
    total = sum(v["realized_pnl_usd"] for v in cap_results.values())
    pos = sum(1 for v in cap_results.values() if v["realized_pnl_usd"] > 0)
    print(f"  TOTAL realized={total:.2f} positive={pos}/5", flush=True)

    out = {
        "baseline": {
            cid: {
                "realized_pnl_usd": baseline_results[cid].realized_pnl_usd,
                "fills": baseline_results[cid].fills,
            }
            for cid in CAPTURE_IDS
        },
        "threshold": THRESHOLD,
        "candidate": cap_results,
    }
    Path("data/mm_directional_flow_sweep_07.json").write_text(
        json.dumps(out, indent=2) + "\n"
    )
    print("DONE", flush=True)


if __name__ == "__main__":
    sys.exit(main())