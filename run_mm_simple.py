import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(_ROOT))

import argparse
import json
import math
import subprocess

from app.mm.config import V20Config
from app.mm.backtest import run_mm_backtest, _compute_backtest_features
from app.mm.book import L2Snapshot, L2Update
from scripts.v20_event_backtest_capture import load_snapshot, load_events


def clean(x):
    if isinstance(x, float) and (math.isinf(x) or math.isnan(x)):
        return None
    return x


def main() -> int:
    parser = argparse.ArgumentParser(description="Run V20 MM backtest on a single capture")
    parser.add_argument("--capture-dir", type=Path, required=True)
    parser.add_argument("--config", default="app/mm/config.json")
    args = parser.parse_args()

    config, config_sha = V20Config.load_authoritative(args.config)
    assert config.live_order_submission is False, "live submission must stay disabled"
    print(f"config={args.config} sha256={config_sha}", flush=True)
    print(f"half_spread={config.base_half_spread_bps} maker_fee={config.maker_fee_bps} "
          f"taker_fee={config.taker_fee_bps} quote_size_usd={config.quote_size_usd}", flush=True)

    capture_dir = args.capture_dir
    manifest = json.loads((capture_dir / "manifest.json").read_text())
    if manifest.get("bootstrap", {}).get("status") != "BRIDGED":
        print("ERROR: capture bootstrap is not BRIDGED; refusing to backtest")
        return 1

    snapshot = load_snapshot(capture_dir)
    depth, trades, counts = load_events(capture_dir)
    print(f"Loaded: {counts}", flush=True)

    features_list = _compute_backtest_features(depth, snapshot)
    print(f"Computed {len(features_list)} feature sets", flush=True)

    result = run_mm_backtest(snapshot, depth, features_list, config)

    git_commit = "unknown"
    git_dirty = ""
    try:
        git_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=_ROOT, stderr=subprocess.DEVNULL
        ).decode().strip()
        git_dirty = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=_ROOT, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        pass

    report = {
        "capture_id": capture_dir.name,
        "git_commit": git_commit,
        "git_dirty": bool(git_dirty),
        "config_path": str(args.config),
        "config_sha256": config_sha,
        "depth_events": counts["depth_events"],
        "trade_events": counts["trade_events"],
        "pnl_bps": clean(result.pnl_bps),
        "pnl_notional_usd": clean(result.pnl_notional_usd),
        "inventory_mtm_bps": clean(result.inventory_mtm_bps),
        "net_pnl_bps_incl_mtm": clean(result.pnl_bps + result.inventory_mtm_bps),
        "fills": result.fills,
        "cancels": result.cancels,
        "win_rate": clean(result.win_rate),
        "winning_fills": result.winning_fills,
        "losing_fills": result.losing_fills,
        "profit_factor": clean(result.profit_factor),
        "avg_win_bps": clean(result.avg_win_bps),
        "avg_loss_bps": clean(result.avg_loss_bps),
        "max_win_bps": clean(result.max_win_bps),
        "max_loss_bps": clean(result.max_loss_bps),
        "gross_profit_bps": clean(result.gross_profit_bps),
        "gross_loss_bps": clean(result.gross_loss_bps),
        "avg_adverse_selection_bps": clean(result.avg_adverse_selection_bps),
        "as_by_horizon": {str(k): clean(v) for k, v in result.as_by_horizon.items()},
        "avg_realized_pnl_per_fill_bps": clean(result.avg_realized_pnl_per_fill_bps),
        "inventory_max": clean(result.inventory_max),
        "inventory_final": clean(result.inventory_final),
        "gate_pass": result.gate_pass,
        "gate_reasons": result.gate_reasons,
    }

    output_path = capture_dir / "mm_results_v20.json"
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(f"\nSaved results -> {output_path}", flush=True)
    print(f"PnL: {result.pnl_bps:.2f} bps (${result.pnl_notional_usd:.2f})", flush=True)
    print(f"Net PnL (incl MTM): {result.pnl_bps + result.inventory_mtm_bps:.2f} bps", flush=True)
    print(f"Fills: {result.fills}, Cancels: {result.cancels}", flush=True)
    print(f"Win rate: {result.win_rate:.1f}%", flush=True)
    print(f"Avg AS: {result.avg_adverse_selection_bps:.4f} bps", flush=True)
    print(f"Inventory max: {result.inventory_max:.4f}, final: {result.inventory_final:.4f}", flush=True)
    print(f"Gate: {'PASS' if result.gate_pass else 'FAIL'} ({result.gate_reasons})", flush=True)
    print(f"Live order submission: DISABLED", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
