"""Economic attribution analysis for V20-ECO-V1.

For each capture, decomposes the realized cash PnL into:
  1. Gross spread capture (what the MM earns from bid-ask spread)
  2. Maker fees / rebate (cost of being a liquidity provider)
  3. Adverse selection (fill price vs future mid — directional bleed)
  4. Execution effects (crossing penalty when quotes are suppressed)
  5. Inventory carry (opportunity cost of holding position)
  6. Residual (unexplained)

Input: the EventBacktestResult fields already compute most of these.
This script re-runs the backtest with detailed fill-level attribution.
"""
from __future__ import annotations
import json
import math
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.mm.config import V20Config
from app.mm.event_backtest import run_event_backtest
from scripts.v20_event_backtest_capture import load_snapshot, load_events

CONFIG = "app/mm/config_v20_eco_v1_actual_fees.json"
CAPTURE_IDS = ["3b8eee35", "477cf6ae", "9863cf18", "e4153485", "ebe81a64"]


def clean(x: float) -> float | None:
    if isinstance(x, float) and (math.isinf(x) or math.isnan(x)):
        return None
    return x


def _attribution(result, config: V20Config) -> dict:
    gross_spread = result.gross_spread_capture_usd
    fees = result.fees_usd
    adverse_selection = result.adverse_selection_usd
    execution_effects = result.execution_effects_usd
    inventory_mtm = result.inventory_mtm_usd
    realized = result.realized_pnl_usd
    net = result.net_pnl_usd

    attribution_sum = gross_spread + fees - adverse_selection + execution_effects
    residual = realized - attribution_sum

    return {
        "fills": result.fills,
        "filled_qty_btc": round(result.filled_qty, 6),
        "realized_pnl_usd": round(realized, 2),
        "net_pnl_usd": round(net, 2),
        "inventory_mtm_usd": round(inventory_mtm, 2),
        "final_inventory_btc": round(result.final_inventory, 6),
        "inventory_max_usd": round(result.inventory_max, 2),
        "inventory_limit_breaches": result.inventory_limit_breaches,
        "--- attribution ---": None,
        "gross_spread_capture_usd": round(gross_spread, 2),
        "maker_fees_net_usd": round(fees, 2),
        "adverse_selection_usd": round(adverse_selection, 2),
        "execution_effects_usd": round(execution_effects, 2),
        "attribution_sum_vs_realized": round(attribution_sum, 2),
        "residual_usd": round(residual, 2),
        "toxicity_suppressed_quotes": result.toxicity_suppressed_quotes,
    }


def main() -> int:
    config, config_sha = V20Config.load_authoritative(CONFIG)
    print(f"Config: {CONFIG}")
    print(f"  maker_fee={config.maker_fee_bps} bps  maker_rebate={config.maker_rebate_bps} bps")
    print(f"  net_maker_fee={config.maker_fee_bps - config.maker_rebate_bps} bps")
    print(f"  base_half_spread={config.base_half_spread_bps} bps  toxicity_filter={config.toxicity_filter_enabled}")
    print(f"  max_position_notional=${config.max_position_notional_usd}")
    print(f"  sha256={config_sha}")
    print()

    captures_root = Path("data/captures")
    scenario_results: dict = {}

    for scenario_name, rebate_bps in [("0.0_bps", 0.0), ("0.35_bps", 0.35), ("1.0_bps", 1.0)]:
        cfg = replace(config, maker_rebate_bps=rebate_bps)
        net_fee = cfg.maker_fee_bps - rebate_bps
        print(f"=== Scenario: maker_rebate={rebate_bps} bps (net_maker_fee={net_fee:.2f} bps) ===")
        print(f"{'capture':<16} {'fills':>6} {'realized':>12} {'net':>10} {'gross_sprd':>12} {'fees':>8} {'adv_sel':>10} {'exec_eff':>10} {'inv_mtm':>10} {'resid':>10} {'inv_max':>10} {'brk':>5}")
        print("-" * 150)

        scenario_data = {}
        for cid in CAPTURE_IDS:
            capture_dirs = sorted(captures_root.glob(f"{cid}*"))
            if not capture_dirs:
                print(f"  {cid}: NOT FOUND")
                continue
            capture_dir = capture_dirs[0]
            snapshot = load_snapshot(capture_dir)
            depth, trades, counts = load_events(capture_dir)
            result = run_event_backtest(snapshot, depth, trades, cfg)

            attr = _attribution(result, cfg)
            scenario_data[capture_dir.name] = attr

            print(
                f"{cid:<16} {result.fills:>6} "
                f"{result.realized_pnl_usd:>12.2f} {result.net_pnl_usd:>10.2f} "
                f"{result.gross_spread_capture_usd:>12.2f} {result.fees_usd:>8.2f} "
                f"{result.adverse_selection_usd:>10.2f} {result.execution_effects_usd:>10.2f} "
                f"{result.inventory_mtm_usd:>10.2f} {attr['residual_usd']:>10.2f} "
                f"{result.inventory_max:>10.2f} {result.inventory_limit_breaches:>5}",
                flush=True,
            )

        total_realized = sum(r["realized_pnl_usd"] for r in scenario_data.values())
        total_gross = sum(r["gross_spread_capture_usd"] for r in scenario_data.values())
        total_fees = sum(r["maker_fees_net_usd"] for r in scenario_data.values())
        total_as = sum(r["adverse_selection_usd"] for r in scenario_data.values())
        total_exec = sum(r["execution_effects_usd"] for r in scenario_data.values())
        total_mtm = sum(r["inventory_mtm_usd"] for r in scenario_data.values())

        print("-" * 150)
        print(f"{'TOTAL':<16} {sum(r['fills'] for r in scenario_data.values()):>6} "
              f"{total_realized:>12.2f} {total_realized + total_mtm:>10.2f} "
              f"{total_gross:>12.2f} {total_fees:>8.2f} "
              f"{total_as:>10.2f} {total_exec:>10.2f} "
              f"{total_mtm:>10.2f} {total_realized - total_gross - total_fees + total_as - total_exec:>10.2f} "
              f"{max(r['inventory_max_usd'] for r in scenario_data.values()):>10.2f} "
              f"{sum(r['inventory_limit_breaches'] for r in scenario_data.values()):>5}")
        print()

        scenario_results[scenario_name] = {
            "maker_rebate_bps": rebate_bps,
            "net_maker_fee_bps": net_fee,
            "total_realized_pnl_usd": round(total_realized, 2),
            "total_gross_spread_capture_usd": round(total_gross, 2),
            "total_fees_usd": round(total_fees, 2),
            "total_adverse_selection_usd": round(total_as, 2),
            "total_execution_effects_usd": round(total_exec, 2),
            "total_inventory_mtm_usd": round(total_mtm, 2),
            "captures": scenario_data,
        }

    out_path = Path("data/mm_backtest_results_v20_eco_v1_attribution.json")
    out_path.write_text(json.dumps(scenario_results, indent=2, allow_nan=False) + "\n")
    print(f"Saved attribution results -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
