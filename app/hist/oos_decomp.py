"""Diagnostic decomposition of the OOS failure. Reads frozen artifacts only.

This is NOT an optimization step and NEVER re-fits or re-tunes the signal.
It consumes the already-computed, untouched OOS runs (oos_oos.json written by
app/hist/oos_test.py) and answers one question:

  Where do ~+1.7..+2.1 gross bps go before they become negative net?

Decomposition chain (all bps, per condition x horizon, per OOS 146 days):

  info_edge      = gross_mean_bps                      (0-cost information)
  - spread       = spread_total (0 here, both legs assumed passive)
  - slippage     = measured adverse-execution assumption, SLIP_BPS/side
  - market impact= impact_total (0 here, not modelled for these sizes)
  - adverse_sel  = gross - E[fill return]              (measured, fill model)
  fill_edge      = E[fill return]                      (what a passive fill keeps)
  - maker fee    = 2 * maker_bps_per_side
  net_maker      = fill_edge - maker_fee               (passive execution view)
  - (taker fee + remaining slip)                       (baseline model bridge)
  net            = gross_mean_bps - cost_bps           (declared baseline)

The key output is the BREAK-EVEN round-trip cost per condition x horizon:
  cost_bps where net = 0.  If break-even < realistic execution cost, the edge
  is a real information effect but is not economically tradeable.

Usage:  python -m app.hist.oos_decomp [--split oos]
"""

import argparse
import json
from pathlib import Path

import numpy as np

from .cond import FEE_BPS, SLIP_BPS, HORIZONS_MS

ROOT = Path("data") / "hist"
MAKER_FEE_BPS = 1.0  # costmodel maker assumption per side

COST_GRID_BPS = (0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0)


def load(split):
    return json.loads((ROOT / "research" / ("oos_%s.json" % split)).read_text())


def decompose(p):
    rows = []
    for r in p["rows"]:
        gross = r["gross_mean_bps"]
        fill = r["fill"]
        e_fill = fill["e_fill_return_bps"]
        adverse = r["gross_mean_bps"] - e_fill
        taker_fee = 2 * FEE_BPS
        slip = 2 * SLIP_BPS
        declared_cost = r["cost_bps"]
        net = r["net_mean_bps@%g" % declared_cost]
        maker_cost = 2 * MAKER_FEE_BPS
        net_maker = e_fill - maker_cost
        breakeven = gross  # cost_bps where gross - cost = 0
        breakeven_passive = e_fill  # cost_bps where fill_edge - cost = 0
        rows.append({
            "label": r["label"], "direction": r["direction"],
            "horizon_ms": r["horizon_ms"], "n": r["n"], "days": r["days"],
            "info_edge_bps": round(gross, 3),
            "spread_bps": 0.0,
            "slippage_bps": round(slip, 1),
            "market_impact_bps": 0.0,
            "adverse_selection_bps": round(-adverse, 3),
            "fill_edge_bps": round(e_fill, 3),
            "maker_fee_bps": round(maker_cost, 1),
            "net_maker_bps": round(net_maker, 3),
            "taker_fee_bps": round(taker_fee, 1),
            "declared_cost_bps": declared_cost,
            "net_bps": round(net, 3),
            "breakeven_cost_bps": round(breakeven, 2),
            "breakeven_passive_cost_bps": round(breakeven_passive, 2),
        })
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="oos", choices=("oos", "train", "validation"))
    args = ap.parse_args(argv)

    p = load(args.split)
    rows = decompose(p)
    payload = {"split": args.split, "lo": p["lo"], "hi": p["hi"], "days": p["days"],
               "maker_fee_per_side_bps": MAKER_FEE_BPS,
               "taker_fee_per_side_bps": FEE_BPS, "slip_per_side_bps": SLIP_BPS,
               "declared_round_trip_bps": p["cost_bps"],
               "rows": rows}
    out = ROOT / "research"
    out.mkdir(parents=True, exist_ok=True)
    (out / ("oos_%s_DECOMP.json" % args.split)).write_text(json.dumps(payload, indent=1))
    (out / ("oos_%s_DECOMP.md" % args.split)).write_text(render_md(payload))
    print("decomp -> %s" % (out / ("oos_%s_DECOMP.md" % args.split)))
    print_breakeven(payload)
    return 0


def render_md(p):
    L = ["# OOS failure decomposition — split %s (%d days: %s .. %s)"
         % (p["split"], p["days"], p["lo"], p["hi"]),
         "",
         "- Source: untouched OOS run, frozen signal (see oos_FROZEN_SPEC.md).",
         "- This document is diagnostic only. No re-fitting, no re-tuning.",
         "- All figures in bps of forward return (thinned events).",
         "",
         "## Chain (per condition x horizon)", "",
         "| condition | dir | h | info | spread | slip | impact | AS | fill | maker-fee | net(maker) | net(declared %g) |"
         % p["declared_round_trip_bps"],
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in p["rows"]:
        L.append("| %s | %s | %ds | %+.2f | %+.2f | %+.2f | %+.2f | %+.2f | %+.2f | %+.2f | %+.2f | %+.2f |" % (
            r["label"], r["direction"], r["horizon_ms"] // 1000,
            r["info_edge_bps"], r["spread_bps"], r["slippage_bps"],
            r["market_impact_bps"], r["adverse_selection_bps"], r["fill_edge_bps"],
            r["maker_fee_bps"], r["net_maker_bps"], r["net_bps"]))
    L += ["", "## Break-even round-trip cost (the critical output)", "",
          "| condition | dir | h | n | break-even (gross view) | break-even (passive/fill view) |",
          "|---|---|---|---|---|---|"]
    for r in p["rows"]:
        L.append("| %s | %s | %ds | %d | %.2f bps | %.2f bps |" % (
            r["label"], r["direction"], r["horizon_ms"] // 1000, r["n"],
            r["breakeven_cost_bps"], r["breakeven_passive_cost_bps"]))
    L += ["", "## Reading the result", "",
          "- break-even (gross view) > realistic round-trip cost  =>  the edge", 
          "  survives execution costs.",
          "- break-even < realistic cost  =>  the ~+2 bps is a real information",
          "  effect that is NOT economically tradeable at current assumptions.",
          "- break-even (passive view) uses the adverse-selection-corrected fill",
          "  return; it is the strictest gate and is always lower.",
          "- Long and short are deliberately reported separately.", ""]
    return "\n".join(L) + "\n"


def print_breakeven(p):
    print("\nBREAK-EVEN COST (round-trip bps), gross view — OOS %s" % p["split"])
    print("  condition     5s    15s   30s   60s")
    for dec in ("10", "1"):
        dname = "long" if dec == "10" else "short"
        key = "%s_%s" % (dec, dname)
        vals = {r["horizon_ms"]: r["breakeven_cost_bps"] for r in p["rows"] if r["label"] == key}
        print("  %-9s%s %4.2f %4.2f %4.2f %4.2f" % (
            key, "  ",
            vals.get(5000, 0), vals.get(15000, 0), vals.get(30000, 0), vals.get(60000, 0)))
    lows = min(p["rows"], key=lambda r: abs(r["breakeven_cost_bps"] - 1))
    print("\nLowest breakeven: %s @%ds = %.2f bps" % (
        lows["label"], lows["horizon_ms"] // 1000, lows["breakeven_cost_bps"]))


if __name__ == "__main__":
    import sys
    sys.exit(main())