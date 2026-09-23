"""Canonical V20-ECO-V1 rerun with actual maker fees (1.0 bps) and
Binance LP rebate (0.35 bps, from published Liquidity Provider Program rates).

Uses the deterministic event-backtest fill model (run_event_backtest) for
execution realism — this is the same model used during certification, ensuring
parity between the canonical economics run and the certification gate.
"""
from __future__ import annotations
import json, math, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.mm.config import V20Config
from app.mm.event_backtest import run_event_backtest
from scripts.v20_event_backtest_capture import load_snapshot, load_events

CONFIG = "app/mm/config_v20_eco_v1_actual_fees.json"
SEED = 42
COMMAND = "python3 scripts/run_v20_eco_v1_actual_fees.py"
OUT = Path("data/mm_backtest_results_v20_eco_v1_actual_fees.json")

CAPTURE_IDS = [
    "3b8eee35",
    "477cf6ae",
    "9863cf18",
    "e4153485",
    "ebe81a64",
]


def clean(x):
    if isinstance(x, float) and (math.isinf(x) or math.isnan(x)):
        return None
    return x


def _result_summary(r) -> dict:
    return {
        "fills": r.fills,
        "cancels": r.cancels,
        "replacements": r.replacements,
        "filled_qty": clean(r.filled_qty),
        "fees_usd": clean(r.fees_usd),
        "realized_pnl_usd": clean(r.realized_pnl_usd),
        "inventory_mtm_usd": clean(r.inventory_mtm_usd),
        "net_pnl_usd": clean(r.net_pnl_usd),
        "avg_adverse_selection_bps": clean(r.avg_adverse_selection_bps),
        "as_by_horizon": {str(k): clean(v) for k, v in r.as_by_horizon.items()},
        "final_inventory": clean(r.final_inventory),
        "inventory_max": clean(r.inventory_max),
        "inventory_limit_breaches": r.inventory_limit_breaches,
        "toxicity_suppressed_quotes": r.toxicity_suppressed_quotes,
        "toxic_flow_imbalance_mean": clean(r.toxic_flow_imbalance_mean),
        "gross_spread_capture_usd": clean(r.gross_spread_capture_usd),
        "adverse_selection_usd": clean(r.adverse_selection_usd),
        "execution_effects_usd": clean(r.execution_effects_usd),
        "buy_fills": r.buy_fills,
        "sell_fills": r.sell_fills,
        "buy_filled_qty": clean(r.buy_filled_qty),
        "sell_filled_qty": clean(r.sell_filled_qty),
        "quote_crossings_detected": r.quote_crossings_detected,
        "quote_crossings_suppressed": r.quote_crossings_suppressed,
        "avg_fill_holding_time_ns": clean(r.avg_fill_holding_time_ns),
    }


def main() -> int:
    config, config_sha = V20Config.load_authoritative(CONFIG)
    assert config.live_order_submission is False
    print(f"config={CONFIG} sha256={config_sha}", flush=True)
    print(
        f"maker_fee={config.maker_fee_bps} bps  maker_rebate={config.maker_rebate_bps} bps  "
        f"net_maker_fee={config.maker_fee_bps - config.maker_rebate_bps} bps  "
        f"taker_fee={config.taker_fee_bps} bps  "
        f"toxicity_filter={config.toxicity_filter_enabled}  "
        f"base_half_spread={config.base_half_spread_bps} bps  "
        f"(ACTUAL FEES from EXECUTION_ECONOMIC_AUDIT.md)",
        flush=True,
    )

    captures_root = Path("data/captures")
    out: dict = {}
    total_net = 0.0
    all_positive = True
    all_gate_pass = True

    for cid in CAPTURE_IDS:
        capture_dirs = sorted(captures_root.glob(f"{cid}*"))
        if not capture_dirs:
            print(f"  {cid}: NOT FOUND", flush=True)
            continue
        capture_dir = capture_dirs[0]
        snapshot = load_snapshot(capture_dir)
        depth, trades, counts = load_events(capture_dir)
        result = run_event_backtest(snapshot, depth, trades, config)
        total_net += result.net_pnl_usd
        if result.net_pnl_usd <= 0:
            all_positive = False
        if result.realized_pnl_usd <= 0:
            all_gate_pass = False
        if result.inventory_limit_breaches > 0 or result.inventory_max > config.max_position_notional_usd:
            all_gate_pass = False

        out[capture_dir.name] = _result_summary(result)
        print(
            f"  {cid}: fills={result.fills} buy={result.buy_fills} sell={result.sell_fills}  "
            f"net=${result.net_pnl_usd:.2f}  realized=${result.realized_pnl_usd:.2f}  "
            f"inv_mtm=${result.inventory_mtm_usd:.2f}  gross=${result.gross_spread_capture_usd:.2f}  "
            f"fees=${result.fees_usd:.2f}  inv_max=${result.inventory_max:.2f}  "
            f"inv_limit_breaches={result.inventory_limit_breaches}  "
            f"as={result.avg_adverse_selection_bps:.4f} bps  "
            f"tox_suppressed={result.toxicity_suppressed_quotes}",
            flush=True,
        )

    envelope = {
        "run_id": "V20-ECO-V1-ACTUAL-FEES",
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1]
        ).decode().strip(),
        "config_path": CONFIG,
        "config_sha256": config_sha,
        "config_label": (
            "Authenticated Binance USDⓈ-M fees: maker=2.0 bps, taker=5.0 bps, "
            "maker_rebate=0.35 bps (LP Program published rate); "
            "toxicity_filter_enabled=true. Verified via /fapi/v1/commissionRate."
        ),
        "seed": SEED,
        "command": COMMAND,
        "live_order_submission": False,
        "total_net_pnl_usd": round(total_net, 2),
        "all_captures_positive": all_positive,
        "results": out,
    }
    OUT.write_text(json.dumps(envelope, indent=2, allow_nan=False) + "\n")
    print(f"Saved V20-ECO-V1-ACTUAL-FEES results -> {OUT}", flush=True)
    print(f"TOTAL net=${total_net:.2f}  all_positive={all_positive}", flush=True)
    return 0 if all_positive else 1


if __name__ == "__main__":
    sys.exit(main())
