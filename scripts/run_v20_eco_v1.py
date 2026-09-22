"""Canonical V20-ECO-V1 rerun from pinned revision.

Provenance: git commit + config SHA-256 + capture SHA-256 (via
data/captures/<id>/provenance.json) + seed + exact command.
Strict JSON (allow_nan=False): non-finite PF/stats become null deliberately.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.mm.config import V20Config
from app.mm.backtest import run_all_mm_backtests

CONFIG = "app/mm/config.json"
SEED = 42
COMMAND = "python3 scripts/run_v20_eco_v1.py"
OUT = Path("data/mm_backtest_results_v20_eco_v1.json")


def clean(x):
    if isinstance(x, float) and (math.isinf(x) or math.isnan(x)):
        return None
    return x


def main() -> int:
    config, config_sha = V20Config.load_authoritative(CONFIG)
    assert config.live_order_submission is False, "live submission must stay disabled"
    print(f"config={CONFIG} sha256={config_sha}", flush=True)
    print(f"base_half_spread={config.base_half_spread_bps} maker_fee={config.maker_fee_bps} "
          f"(SCENARIO ASSUMPTION, not verified live fees)", flush=True)

    results = run_all_mm_backtests(
        "data/captures",
        config,
        config_path=CONFIG,
        seed=SEED,
        command=COMMAND,
    )

    out: dict = {}
    for capture_id, r in results.items():
        out[capture_id] = {
            "pnl_bps": clean(r.pnl_bps),
            "pnl_notional_usd": clean(r.pnl_notional_usd),
            "inventory_mtm_bps": clean(r.inventory_mtm_bps),
            "net_pnl_bps_incl_mtm": clean(r.pnl_bps + r.inventory_mtm_bps),
            "fills": r.fills,
            "cancels": r.cancels,
            "win_rate": clean(r.win_rate),
            "winning_fills": r.winning_fills,
            "losing_fills": r.losing_fills,
            "profit_factor": clean(r.profit_factor),
            "avg_win_bps": clean(r.avg_win_bps),
            "avg_loss_bps": clean(r.avg_loss_bps),
            "max_win_bps": clean(r.max_win_bps),
            "max_loss_bps": clean(r.max_loss_bps),
            "gross_profit_bps": clean(r.gross_profit_bps),
            "gross_loss_bps": clean(r.gross_loss_bps),
            "avg_adverse_selection_bps": clean(r.avg_adverse_selection_bps),
            "as_by_horizon": {str(k): clean(v) for k, v in r.as_by_horizon.items()},
            "avg_realized_pnl_per_fill_bps": clean(r.avg_realized_pnl_per_fill_bps),
            "inventory_max": clean(r.inventory_max),
            "inventory_final": clean(r.inventory_final),
            "gate_pass": r.gate_pass,
            "gate_reasons": r.gate_reasons,
        }

    envelope = {
        "run_id": "V20-ECO-V1",
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip(),
        "config_path": CONFIG,
        "config_sha256": config_sha,
        "config_label": "SCENARIO ASSUMPTION: base_half_spread 2.5bps, maker_fee 0.0bps — not verified live fees",
        "seed": SEED,
        "command": COMMAND,
        "live_order_submission": False,
        "results": out,
    }
    OUT.write_text(json.dumps(envelope, indent=2, allow_nan=False) + "\n")
    print(f"Saved V20-ECO-V1 results -> {OUT}", flush=True)
    for capture_id, r in out.items():
        print(f"  {capture_id[:12]}: PnL={r['pnl_bps']:.2f} bps, "
              f"fills={r['fills']}, gate={'PASS' if r['gate_pass'] else 'FAIL'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
