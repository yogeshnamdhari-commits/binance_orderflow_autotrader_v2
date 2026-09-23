"""V20-ECO-V1 realized-fee backtest using authentic event-driven fills.

This script replays actual Binance depth + trade events through the
``PassiveQuoteReplay`` fill model, so every fill is attributable to an
observed aggressive trade crossing the passive quote.  This replaces the
probabilistic ``simulate_fill`` model used in V20-ECO-V1-SIM.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.mm.config import V20Config
from app.mm.event_backtest import run_event_backtest

CONFIG = "app/mm/config_v20_eco_v1_actual_fees.json"
CAPS_DIR = "data/captures"
OUT = Path("data/mm_backtest_results_v20_eco_v1.json")
SEED = 42
COMMAND = "python3 scripts/run_v20_eco_v1.py"


def clean(x):
    if isinstance(x, float) and (math.isinf(x) or math.isnan(x)):
        return None
    return x


def main() -> int:
    config, config_sha = V20Config.load_authoritative(CONFIG)
    assert config.live_order_submission is False
    print(f"config={CONFIG} sha256={config_sha}", flush=True)
    print(
        f"maker_fee={config.maker_fee_bps} bps "
        f"maker_rebate={config.maker_rebate_bps} bps "
        f"net_rate={config.maker_fee_bps - config.maker_rebate_bps} bps "
        f"base_half_spread={config.base_half_spread_bps} "
        f"toxicity_filter={config.toxicity_filter_enabled}",
        flush=True,
    )

    from scripts.v20_event_backtest_capture import load_snapshot, load_events

    out: dict = {}
    all_pass = True

    for capture_dir in sorted(Path(CAPS_DIR).iterdir()):
        if not capture_dir.is_dir():
            continue
        snapshot_file = capture_dir / "snapshot.json"
        events_file = capture_dir / "events.jsonl"
        if not snapshot_file.exists() or not events_file.exists():
            continue

        print(f"Processing {capture_dir.name}...", flush=True)
        snapshot = load_snapshot(capture_dir)
        depth, trades, counts = load_events(capture_dir)

        result = run_event_backtest(
            snapshot, depth, trades, config,
            horizon_ms=(1, 5, 10, 25, 50, 100),
        )

        net_pnl_bps = clean(result.net_pnl_usd / config.quote_size_usd * 10_000.0)
        gross_spread_bps = clean(
            result.gross_spread_capture_usd / config.quote_size_usd * 10_000.0
        )
        inv_mtm_bps = clean(
            result.inventory_mtm_usd / config.quote_size_usd * 10_000.0
        )
        realized_pnl_bps = clean(
            result.realized_pnl_usd / config.quote_size_usd * 10_000.0
        )

        inventory_within_limit = (
            result.inventory_max <= config.max_position_notional_usd + 1e-6
        )
        no_inventory_breaches = result.inventory_limit_breaches == 0
        realized_pnl_positive = result.realized_pnl_usd > 0
        net_pnl_positive = result.net_pnl_usd > 0
        sufficient_fills = result.fills > 0

        gate_pass = all([
            sufficient_fills,
            realized_pnl_positive,
            net_pnl_positive,
            inventory_within_limit,
            no_inventory_breaches,
        ])
        if not gate_pass:
            all_pass = False
        gate_reasons: list[str] = []
        if not sufficient_fills:
            gate_reasons.append("insufficient_fills")
        if not realized_pnl_positive:
            gate_reasons.append("realized_pnl_not_positive")
        if not net_pnl_positive:
            gate_reasons.append("net_pnl_not_positive")
        if not inventory_within_limit:
            gate_reasons.append(
                f"inventory_exceeds_limit ({result.inventory_max:.2f} > {config.max_position_notional_usd})"
            )
        if not no_inventory_breaches:
            gate_reasons.append(f"inventory_limit_breached ({result.inventory_limit_breaches}x)")

        out[capture_dir.name] = {
            "pnl_bps": realized_pnl_bps,
            "pnl_notional_usd": clean(result.realized_pnl_usd),
            "inventory_mtm_bps": inv_mtm_bps,
            "net_pnl_bps_incl_mtm": net_pnl_bps,
            "fills": result.fills,
            "cancels": result.cancels,
            "replacements": result.replacements,
            "win_rate": None,
            "winning_fills": None,
            "losing_fills": None,
            "profit_factor": None,
            "avg_win_bps": None,
            "avg_loss_bps": None,
            "max_win_bps": None,
            "max_loss_bps": None,
            "gross_profit_bps": None,
            "gross_loss_bps": None,
            "avg_adverse_selection_bps": clean(result.avg_adverse_selection_bps),
            "as_by_horizon": {str(k): clean(v) for k, v in result.as_by_horizon.items()},
            "avg_realized_pnl_per_fill_bps": clean(
                result.realized_pnl_usd / max(result.fills, 1) / config.quote_size_usd * 10_000.0
            ),
            "inventory_max": clean(result.inventory_max),
            "inventory_max_bps": clean(result.inventory_max / config.quote_size_usd * 10_000.0),
            "inventory_final": clean(result.final_inventory),
            "inventory_limit_breaches": result.inventory_limit_breaches,
            "gate_pass": gate_pass,
            "gate_reasons": gate_reasons if gate_reasons else ["pass"],
            "fees_usd": clean(result.fees_usd),
            "gross_spread_capture_bps": gross_spread_bps,
            "buy_fills": result.buy_fills,
            "sell_fills": result.sell_fills,
            "toxicity_suppressed_quotes": result.toxicity_suppressed_quotes,
        }

        print(
            f"  PnL: {net_pnl_bps:.2f} bps (${result.net_pnl_usd:.2f}), "
            f"realized: {realized_pnl_bps:.2f} bps (${result.realized_pnl_usd:.2f}), "
            f"Fills: {result.fills}, Fees: ${result.fees_usd:.2f}, "
            f"Gross spread: {gross_spread_bps:.2f} bps, "
            f"inv_max: ${result.inventory_max:.2f} ({result.inventory_limit_breaches} breaches)",
            flush=True,
        )
        print(f"  Gate: {'PASS' if gate_pass else 'FAIL'} {gate_reasons}", flush=True)
        print(flush=True)

    git_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1]
    ).decode().strip()

    envelope = {
        "run_id": "V20-ECO-V1",
        "git_commit": git_commit,
        "config_path": CONFIG,
        "config_sha256": config_sha,
        "config_label": "ACTUAL FEES: maker 1.0 bps, taker 2.0 bps, maker rebate 0.35 bps (Binance LP Program rate from EXECUTION_ECONOMIC_AUDIT.md; verify via /fapi/v1/commissionRate)",
        "seed": SEED,
        "command": COMMAND,
        "live_order_submission": False,
        "fill_model": "event_driven",
        "results": out,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(envelope, indent=2, allow_nan=False) + "\n")
    print(f"Saved V20-ECO-V1 results -> {OUT}", flush=True)
    for capture_id, r in out.items():
        print(
            f"  {capture_id[:12]}: PnL={r['net_pnl_bps_incl_mtm']:.2f} bps, "
            f"fills={r['fills']}, gate={'PASS' if r['gate_pass'] else 'FAIL'}",
            flush=True,
        )
    print(f"\nAll gates PASS: {all_pass}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
