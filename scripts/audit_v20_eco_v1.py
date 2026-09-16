"""Audit V20-ECO-V1 canonical rerun: NetPnL + AS curve + fee labeling."""
from __future__ import annotations

import json
import sys
from pathlib import Path

RESULT = Path("data/mm_backtest_results_v20_eco_v1.json")


def main() -> None:
    env = json.loads(RESULT.read_text())
    print(f"run_id={env.get('run_id')} git={env.get('git_commit')} "
          f"config_sha={env.get('config_sha256')} seed={env.get('seed')}")
    print(f"config_label={env.get('config_label')}")
    print(f"live_order_submission={env.get('live_order_submission')}")
    print()
    hdr = (f"{'capture':32} {'fills':>6} {'canc':>5} {'WR%':>6} {'PF':>8} "
           f"{'real_bps':>10} {'mtm_bps':>10} {'net_bps':>10} {'notion$':>10} {'gate':>5}")
    print(hdr)
    for cap, r in sorted(env["results"].items()):
        pf = r["profit_factor"]
        pf_s = "null" if pf is None else f"{pf:.2f}"
        print(f"{cap:32} {r['fills']:6d} {r['cancels']:5d} "
              f"{(r['win_rate'] or 0):6.2f} {pf_s:>8} "
              f"{r['pnl_bps']:10.2f} {r['inventory_mtm_bps']:10.2f} "
              f"{r['net_pnl_bps_incl_mtm']:10.2f} {r['pnl_notional_usd']:10.2f} "
              f"{'PASS' if r['gate_pass'] else 'FAIL':>5}")
    print()
    print("Adverse-selection curves AS(horizon ticks):")
    for cap, r in sorted(env["results"].items()):
        curve = ", ".join(f"{h}={r['as_by_horizon'][h]:.3f}" for h in
                          sorted(r["as_by_horizon"], key=int))
        print(f"  {cap[:8]}: {curve}  (avg10={r['avg_adverse_selection_bps']:.3f})")
    print()
    print("Per-capture gate reasons / inventory:")
    for cap, r in sorted(env["results"].items()):
        print(f"  {cap[:8]}: gate={r['gate_reasons']} inv_max={r['inventory_max']:.5f} "
              f"inv_final={r['inventory_final']:.6f} avgwin={r['avg_win_bps']} "
              f"avgloss={r['avg_loss_bps']}")


if __name__ == "__main__":
    sys.exit(main())
