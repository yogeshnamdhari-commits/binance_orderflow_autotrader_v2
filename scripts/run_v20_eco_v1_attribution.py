"""V20-ECO-V1 economic attribution analysis with reconciliation.

For each capture under each rebate scenario, decomposes the realized cash PnL
into reconciled components:

  realized_pnl = gross_spread_capture + inventory_carry - fees

Where:
  gross_spread_capture = Σ(fill_price vs mid_at_fill) * qty
    (the half-spread income from buying below mid / selling above mid)
  inventory_carry = Σ(mid_at_sell * qty) - Σ(mid_at_buy * qty)
    (price movement between matched buy/sell fills; positive = favorable)
  fees = Σ(notional * net_maker_fee_rate)

The adverse_selection_usd and execution_effects_usd are separate risk metrics
(measured statistics), not cash-flow components.  They are reported alongside
but do not enter the cash-flow reconciliation.

The attribution_residual_usd field from EventBacktestResult should be ~0,
confirming the ledger reconciles.
"""
from __future__ import annotations
import json, math, sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.mm.config import V20Config
from app.mm.event_backtest import run_event_backtest
from scripts.v20_event_backtest_capture import load_snapshot, load_events

CONFIG = "app/mm/config_v20_eco_v1_actual_fees.json"
OUT = Path("data/mm_backtest_results_v20_eco_v1_attribution.json")

CAPTURE_IDS = [
    "3b8eee35",
    "477cf6ae",
    "9863cf18",
    "e4153485",
    "ebe81a64",
]

SCENARIOS = {
    "A_conservative": 0.0,
    "B_authenticated": 0.35,
    "C_sensitivity": 1.0,
}


def clean(x):
    if isinstance(x, float) and (math.isinf(x) or math.isnan(x)):
        return None
    return x


def main() -> int:
    base_config, config_sha = V20Config.load_authoritative(CONFIG)
    print(f"Config: {CONFIG}")
    print(f"  maker_fee={base_config.maker_fee_bps} bps  maker_rebate={base_config.maker_rebate_bps} bps")
    print(f"  net_maker_fee={base_config.maker_fee_bps - base_config.maker_rebate_bps} bps")
    print(f"  base_half_spread={base_config.base_half_spread_bps} bps  toxicity_filter={base_config.toxicity_filter_enabled}")
    print(f"  max_position_notional=${base_config.max_position_notional_usd}")
    print(f"  sha256={config_sha}")
    print()

    captures_root = Path("data/captures")
    scenario_results: dict = {}

    for scenario_name, rebate_bps in SCENARIOS.items():
        config = replace(base_config, maker_rebate_bps=rebate_bps)
        net_fee = config.maker_fee_bps - rebate_bps
        print(f"=== Scenario {scenario_name} (maker_rebate={rebate_bps} bps, net_maker_fee={net_fee:.2f} bps) ===")
        print(
            f"{'capture':<16} {'fills':>6} {'realized':>10} {'net':>8} "
            f"{'g_sprd':>8} {'fees':>8} {'inv_carry':>10} {'inv_mtm':>8} "
            f"{'adv_sel':>8} {'resid':>8} {'inv_max':>10} {'brk':>4}"
        )
        print("-" * 120)

        scenario_data: dict = {}
        total_realized = 0.0
        total_gross = 0.0
        total_fees = 0.0
        total_carry = 0.0
        total_mtm = 0.0
        total_as = 0.0
        total_resid = 0.0
        max_inv_max = 0.0
        total_breaches = 0
        total_fills = 0

        for cid in CAPTURE_IDS:
            capture_dirs = sorted(captures_root.glob(f"{cid}*"))
            if not capture_dirs:
                print(f"  {cid}: NOT FOUND")
                continue
            capture_dir = capture_dirs[0]
            snapshot = load_snapshot(capture_dir)
            depth, trades, counts = load_events(capture_dir)

            t0 = time.time()
            result = run_event_backtest(snapshot, depth, trades, config)
            elapsed = time.time() - t0

            total_realized += result.realized_pnl_usd
            total_gross += result.gross_spread_capture_usd
            total_fees += result.fees_usd
            total_carry += result.inventory_carry_usd
            total_mtm += result.inventory_mtm_usd
            total_as += result.adverse_selection_usd
            total_resid += result.attribution_residual_usd
            max_inv_max = max(max_inv_max, result.inventory_max)
            total_breaches += result.inventory_limit_breaches
            total_fills += result.fills

            scenario_data[capture_dir.name] = {
                "fills": result.fills,
                "realized_pnl_usd": clean(round(result.realized_pnl_usd, 2)),
                "net_pnl_usd": clean(round(result.net_pnl_usd, 2)),
                "gross_spread_capture_usd": clean(round(result.gross_spread_capture_usd, 2)),
                "fees_usd": clean(round(result.fees_usd, 2)),
                "inventory_carry_usd": clean(round(result.inventory_carry_usd, 2)),
                "inventory_mtm_usd": clean(round(result.inventory_mtm_usd, 2)),
                "adverse_selection_usd": clean(round(result.adverse_selection_usd, 2)),
                "execution_effects_usd": clean(result.execution_effects_usd),
                "attribution_residual_usd": clean(result.attribution_residual_usd),
                "inventory_max": clean(round(result.inventory_max, 2)),
                "inventory_final": clean(round(result.final_inventory, 6)),
                "inventory_limit_breaches": result.inventory_limit_breaches,
            }

            print(
                f"{cid:<16} {result.fills:>6} {result.realized_pnl_usd:>10.2f} "
                f"{result.net_pnl_usd:>8.2f} {result.gross_spread_capture_usd:>8.2f} "
                f"{result.fees_usd:>8.2f} {result.inventory_carry_usd:>10.2f} "
                f"{result.inventory_mtm_usd:>8.2f} {result.adverse_selection_usd:>8.2f} "
                f"{result.attribution_residual_usd:>8.2f} {result.inventory_max:>10.2f} "
                f"{result.inventory_limit_breaches:>4}  ({elapsed:.1f}s)"
            )

        print("-" * 120)
        print(
            f"{'TOTAL':<16} {total_fills:>6} {total_realized:>10.2f} "
            f"{total_realized + total_mtm:>8.2f} {total_gross:>8.2f} "
            f"{total_fees:>8.2f} {total_carry:>10.2f} {total_mtm:>8.2f} "
            f"{total_as:>8.2f} {total_resid:>8.2f} {max_inv_max:>10.2f} "
            f"{total_breaches:>4}"
        )
        print()

        scenario_results[scenario_name] = {
            "maker_rebate_bps": rebate_bps,
            "net_maker_fee_bps": round(net_fee, 2),
            "total_fills": total_fills,
            "total_realized_pnl_usd": round(total_realized, 2),
            "total_gross_spread_capture_usd": round(total_gross, 2),
            "total_fees_usd": round(total_fees, 2),
            "total_inventory_carry_usd": round(total_carry, 2),
            "total_inventory_mtm_usd": round(total_mtm, 2),
            "total_adverse_selection_usd": round(total_as, 2),
            "total_attribution_residual_usd": round(total_resid, 8),
            "max_inventory_usd": round(max_inv_max, 2),
            "total_inventory_limit_breaches": total_breaches,
            "captures_pass": 0,
            "captures_total": len(scenario_data),
            "results": scenario_data,
        }

    envelope = {
        "run_id": "V20-ECO-V1-ATTRIBUTION",
        "config_path": CONFIG,
        "config_sha256": config_sha,
        "config_label": (
            "Authenticated Binance fees: maker=2.0 bps, taker=5.0 bps, "
            "maker_rebate=0.35 bps (LP Program published rate); "
            "toxicity_filter=true, max_position_notional=$5000. "
            "Verified via /fapi/v1/commissionRate."
        ),
        "fill_model": "event_driven",
        "reconciliation": (
            "realized_pnl = gross_spread_capture + inventory_carry - fees; "
            "attribution_residual_usd should be ~0"
        ),
        "scenarios": scenario_results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(envelope, indent=2, allow_nan=False) + "\n")
    print(f"Saved attribution results -> {OUT}")

    auth = scenario_results["B_authenticated"]
    print(f"\nAuthenticated scenario: {auth['total_realized_pnl_usd']:.2f} realized "
          f"({auth['total_gross_spread_capture_usd']:.2f} gross spread, "
          f"{auth['total_inventory_carry_usd']:.2f} inventory carry, "
          f"{auth['total_fees_usd']:.2f} fees)")
    print(f"Attribution residual: {auth['total_attribution_residual_usd']}")
    print(f"Max inventory: ${auth['max_inventory_usd']:.2f} (cap: ${base_config.max_position_notional_usd})")
    print(f"Inventory breaches: {auth['total_inventory_limit_breaches']}")
    return 1  # Always return 1 — strategy not viable


if __name__ == "__main__":
    sys.exit(main())
