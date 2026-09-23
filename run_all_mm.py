import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(_ROOT))

import json
import math
import subprocess

from app.mm.config import V20Config
from app.mm.backtest import run_all_mm_backtests


def clean(x):
    if isinstance(x, float) and (math.isinf(x) or math.isnan(x)):
        return None
    return x


def main() -> int:
    config, config_sha = V20Config.load_authoritative("app/mm/config.json")
    if config.live_order_submission:
        print("ERROR: live_order_submission is True; refusing to run")
        return 1

    print(f"config=app/mm/config.json sha256={config_sha}", flush=True)
    print(f"half_spread={config.base_half_spread_bps} maker_fee={config.maker_fee_bps} "
          f"taker_fee={config.taker_fee_bps} quote_size_usd={config.quote_size_usd}", flush=True)
    print(f"Live order submission: DISABLED", flush=True)

    results = run_all_mm_backtests(
        "data/captures",
        config,
        config_path="app/mm/config.json",
        seed=42,
        command="python3 run_all_mm.py",
    )

    out = {}
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
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=_ROOT).decode().strip(),
        "config_path": "app/mm/config.json",
        "config_sha256": config_sha,
        "seed": 42,
        "command": "python3 run_all_mm.py",
        "live_order_submission": False,
        "results": out,
    }

    OUT = Path("data/mm_backtest_results_v20_eco_v1.json")
    OUT.write_text(json.dumps(envelope, indent=2, allow_nan=False) + "\n")
    print(f"\nSaved results -> {OUT}", flush=True)
    print()
    for capture_id, r in out.items():
        print(f"  {capture_id[:12]}: PnL={r['pnl_bps']:.2f} bps, fills={r['fills']}, "
              f"gate={'PASS' if r['gate_pass'] else 'FAIL'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
