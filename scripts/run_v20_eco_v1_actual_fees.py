"""Canonical V20-ECO-V1 rerun with actual maker fees (1.0 bps)."""
from __future__ import annotations
import json, math, subprocess, sys
from pathlib import Path
from app.mm.config import V20Config
from app.mm.backtest import run_all_mm_backtests

CONFIG = "app/mm/config_v20_eco_v1_actual_fees.json"
SEED = 42
COMMAND = "python3 scripts/run_v20_eco_v1_actual_fees.py"
OUT = Path("data/mm_backtest_results_v20_eco_v1_actual_fees.json")

def clean(x):
    if isinstance(x, float) and (math.isinf(x) or math.isnan(x)):
        return None
    return x

def main() -> None:
    config, config_sha = V20Config.load_authoritative(CONFIG)
    assert config.live_order_submission is False
    print(f"config={CONFIG} sha256={config_sha}", flush=True)
    print(f"maker_fee={config.maker_fee_bps} taker_fee={config.taker_fee_bps} base_half_spread={config.base_half_spread_bps} (ACTUAL FEES from EXECUTION_ECONOMIC_AUDIT.md)", flush=True)
    results = run_all_mm_backtests("data/captures", config, config_path=CONFIG, seed=SEED, command=COMMAND)
    out: dict = {}
    for capture_id, r in results.items():
        out[capture_id] = {
            "pnl_bps": clean(r.pnl_bps),
            "pnl_notional_usd": clean(r.pnl_notional_usd),
            "inventory_mtm_bps": clean(r.inventory_mtm_bps),
            "net_pnl_bps_incl_mtm": clean(r.pnl_bps + r.inventory_mtm_bps),
            "fills": r.fills, "cancels": r.cancels,
            "win_rate": clean(r.win_rate),
            "winning_fills": r.winning_fills, "losing_fills": r.losing_fills,
            "profit_factor": clean(r.profit_factor),
            "avg_win_bps": clean(r.avg_win_bps), "avg_loss_bps": clean(r.avg_loss_bps),
            "max_win_bps": clean(r.max_win_bps), "max_loss_bps": clean(r.max_loss_bps),
            "gross_profit_bps": clean(r.gross_profit_bps), "gross_loss_bps": clean(r.gross_loss_bps),
            "avg_adverse_selection_bps": clean(r.avg_adverse_selection_bps),
            "as_by_horizon": {str(k): clean(v) for k, v in r.as_by_horizon.items()},
            "avg_realized_pnl_per_fill_bps": clean(r.avg_realized_pnl_per_fill_bps),
            "inventory_max": clean(r.inventory_max), "inventory_final": clean(r.inventory_final),
            "gate_pass": r.gate_pass, "gate_reasons": r.gate_reasons,
        }
    envelope = {
        "run_id": "V20-ECO-V1-ACTUAL-FEES",
        "git_commit": subprocess.check_output(["git","rev-parse","HEAD"]).decode().strip(),
        "config_path": CONFIG, "config_sha256": config_sha,
        "config_label": "ACTUAL FEES: maker 1.0 bps, taker 2.0 bps (from EXECUTION_ECONOMIC_AUDIT.md)",
        "seed": SEED, "command": COMMAND,
        "live_order_submission": False,
        "results": out,
    }
    OUT.write_text(json.dumps(envelope, indent=2, allow_nan=False) + "\n")
    print(f"Saved V20-ECO-V1-ACTUAL-FEES results -> {OUT}", flush=True)

if __name__ == "__main__":
    sys.exit(main())
