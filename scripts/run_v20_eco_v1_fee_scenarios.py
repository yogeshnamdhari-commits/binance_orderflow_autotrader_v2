"""V20-ECO-V1 three-scenario fee sensitivity runner.

Runs the event-driven fill model on all 5 BTCUSDT captures across three
rebate scenarios, applying the strengthened certification gate to each.

Scenarios:
  A — Conservative:   maker_rebate_bps = 0.0   (no rebate assumed)
  B — Authenticated:  maker_rebate_bps = 0.35 (Binance LP Program published rate)
  C — Sensitivity:    maker_rebate_bps = 1.0   (intermediate sensitivity point)

The base config (maker_fee_bps=1.0, taker_fee_bps=2.0, base_half_spread_bps=2.5,
toxicity_filter_enabled=true) is frozen across all scenarios.  Only the
maker_rebate_bps varies, so differences are attributable to the rebate assumption.

Gate (applied per capture):
  - fills > 0
  - realized_pnl_usd > 0
  - net_pnl_usd > 0
  - inventory_max <= max_position_notional_usd
  - inventory_limit_breaches == 0

A capture must PASS the gate under the Authenticated scenario for the
strategy to be considered viable.  The Conservative scenario establishes
whether the strategy survives with zero rebate (the cleanest test of signal
quality).
"""
from __future__ import annotations
import json, math, subprocess, sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.mm.config import V20Config
from app.mm.event_backtest import run_event_backtest
from scripts.v20_event_backtest_capture import load_snapshot, load_events

CONFIG = "app/mm/config_v20_eco_v1_actual_fees.json"
COMMAND = "python3 scripts/run_v20_eco_v1_fee_scenarios.py"
OUT = Path("data/mm_backtest_results_v20_eco_v1_fee_scenarios.json")

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


def _gate_passes(result, config) -> tuple[bool, list[str]]:
    reasons = []
    if result.fills <= 0:
        reasons.append("insufficient_fills")
    if result.realized_pnl_usd <= 0:
        reasons.append("realized_pnl_not_positive")
    if result.net_pnl_usd <= 0:
        reasons.append("net_pnl_not_positive")
    if result.inventory_max > config.max_position_notional_usd + 1e-6:
        reasons.append(f"inventory_exceeds_limit ({result.inventory_max:.2f} > {config.max_position_notional_usd})")
    if result.inventory_limit_breaches > 0:
        reasons.append(f"inventory_limit_breached ({result.inventory_limit_breaches}x)")
    return len(reasons) == 0, reasons


def main() -> int:
    base_config, config_sha = V20Config.load_authoritative(CONFIG)
    assert base_config.live_order_submission is False
    print(f"config={CONFIG} sha256={config_sha}", flush=True)
    print(
        f"maker_fee={base_config.maker_fee_bps} bps  taker_fee={base_config.taker_fee_bps} bps  "
        f"base_half_spread={base_config.base_half_spread_bps} bps  "
        f"toxicity_filter={base_config.toxicity_filter_enabled}  "
        f"max_position_notional=${base_config.max_position_notional_usd}",
        flush=True,
    )
    print(f"Scenarios: {json.dumps({k: f'{v} bps rebate' for k, v in SCENARIOS.items()})}", flush=True)

    captures_root = Path("data/captures")
    all_output: dict = {}
    scenario_results: dict[str, dict] = {}

    for scenario_name, rebate_bps in SCENARIOS.items():
        print(f"\n=== Scenario {scenario_name} (maker_rebate={rebate_bps} bps, net_maker_fee={base_config.maker_fee_bps - rebate_bps:.2f} bps) ===", flush=True)
        config = replace(base_config, maker_rebate_bps=rebate_bps)
        out: dict = {}
        total_net = 0.0
        total_realized = 0.0
        captures_pass = 0

        for cid in CAPTURE_IDS:
            capture_dirs = sorted(captures_root.glob(f"{cid}*"))
            if not capture_dirs:
                print(f"  {cid}: NOT FOUND", flush=True)
                continue
            capture_dir = capture_dirs[0]
            snapshot = load_snapshot(capture_dir)
            depth, trades, counts = load_events(capture_dir)

            t0 = time.time()
            result = run_event_backtest(snapshot, depth, trades, config)
            elapsed = time.time() - t0

            total_net += result.net_pnl_usd
            total_realized += result.realized_pnl_usd
            passes, reasons = _gate_passes(result, config)
            if passes:
                captures_pass += 1

            out[capture_dir.name] = {
                "fills": result.fills,
                "realized_pnl_usd": clean(result.realized_pnl_usd),
                "inventory_mtm_usd": clean(result.inventory_mtm_usd),
                "net_pnl_usd": clean(result.net_pnl_usd),
                "fees_usd": clean(result.fees_usd),
                "gross_spread_capture_usd": clean(result.gross_spread_capture_usd),
                "inventory_max": clean(result.inventory_max),
                "inventory_final": clean(result.final_inventory),
                "inventory_limit_breaches": result.inventory_limit_breaches,
                "avg_as_bps": clean(result.avg_adverse_selection_bps),
                "gate_pass": passes,
                "gate_reasons": reasons if reasons else ["pass"],
            }
            print(
                f"  {cid}: fills={result.fills}  net=${result.net_pnl_usd:.2f}  "
                f"realized=${result.realized_pnl_usd:.2f}  fees=${result.fees_usd:.2f}  "
                f"inv_max=${result.inventory_max:.2f}  breaches={result.inventory_limit_breaches}  "
                f"gate={'PASS' if passes else 'FAIL'}  ({elapsed:.1f}s)",
                flush=True,
            )

        scenario_results[scenario_name] = {
            "maker_rebate_bps": rebate_bps,
            "net_maker_fee_bps": base_config.maker_fee_bps - rebate_bps,
            "total_net_pnl_usd": round(total_net, 2),
            "total_realized_pnl_usd": round(total_realized, 2),
            "captures_pass": captures_pass,
            "captures_total": len(out),
            "results": out,
        }
        print(f"  TOTAL: net=${total_net:.2f}  realized=${total_realized:.2f}  "
              f"captures_pass={captures_pass}/{len(out)}", flush=True)

    envelope = {
        "run_id": "V20-ECO-V1-FEE-SCENARIOS",
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1]
        ).decode().strip(),
        "config_path": CONFIG,
        "config_sha256": config_sha,
        "config_label": (
            "maker_fee=1.0 bps, taker_fee=2.0 bps, base_half_spread=2.5 bps, "
            "toxicity_filter=true from EXECUTION_ECONOMIC_AUDIT.md; "
            f"rebate scenarios: {json.dumps(SCENARIOS)}"
        ),
        "command": COMMAND,
        "fill_model": "event_driven",
        "scenarios": scenario_results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(envelope, indent=2, allow_nan=False) + "\n")
    print(f"\nSaved results -> {OUT}", flush=True)

    auth = scenario_results["B_authenticated"]
    if auth["captures_pass"] == auth["captures_total"]:
        print(f"AUTHENTICATED SCENARIO: {auth['captures_pass']}/{auth['captures_total']} captures PASS "
              f"total_realized=${auth['total_realized_pnl_usd']:.2f}", flush=True)
        return 0
    else:
        print(f"AUTHENTICATED SCENARIO: {auth['captures_pass']}/{auth['captures_total']} captures PASS "
              f"total_realized=${auth['total_realized_pnl_usd']:.2f} — NOT CERTIFIED", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
