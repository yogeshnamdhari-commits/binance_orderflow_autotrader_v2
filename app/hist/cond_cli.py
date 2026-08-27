"""Conditional-expectancy research CLI (Dataset A).

`python -m app.hist.cond --symbol BTCUSDT --start 2026-07-01 --end 2026-07-17`

Pooled decile/exhaustion tables are written to data/hist/research/cond_report.{md,json}.
Net returns include the round-trip cost model (fee + slippage assumptions).
"""

import argparse
import json
import sys
from pathlib import Path

from .cond import day_research, FEE_BPS, SLIP_BPS

FEATURES = ("delta_5s", "buyshare_5s", "intensity_5s", "accel")


def _pool(table, feature):
    rows = []
    for d in table:
        rows.extend(d.get(feature, []) or [])
    if not rows:
        return {}
    out = {}
    for r in rows:
        d = r["decile"]
        agg = out.setdefault(d, {"n": 0, "net_wsum": 0.0, "gross_wsum": 0.0})
        agg["n"] += r["n"]
        agg["net_wsum"] += r["n"] * r["net_mean_bps"]
        agg["gross_wsum"] += r["n"] * r["gross_mean_bps"]
    return {d: {"n": a["n"], "net_mean_bps": round(a["net_wsum"] / a["n"], 3),
                "gross_mean_bps": round(a["gross_wsum"] / a["n"], 3)} for d, a in out.items()}


def _pool_exh(table):
    out = {}
    for side in ("buy", "sell"):
        vals = [d["exhaustion"][side] for d in table if d["exhaustion"][side]]
        if not vals:
            out[side] = None
            continue
        n = sum(v["n"] for v in vals)
        net = sum(v["n"] * v["net_mean_bps"] for v in vals) / n
        out[side] = {"n": n, "net_mean_bps": round(net, 3), "days": len(vals)}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    root = Path(args.out) if args.out else Path("data") / "hist"
    out_dir = root / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    store = root / "normalized" / args.symbol.upper() / "aggTrades"
    files = sorted(store.glob("*.parquet"))
    days = [f.name.split("-aggTrades-")[-1].replace(".parquet", "") for f in files]
    if args.start and args.end:
        keep = [(f, d) for f, d in zip(files, days) if args.start <= d <= args.end]
        files, days = zip(*keep) if keep else ((), ())

    table = []
    for f in files:
        try:
            table.append(day_research(f))
        except Exception as e:
            print("ERR %s %r" % (f, e), flush=True)
    if not table:
        print("no days processed")
        return 1

    pooled = {f: _pool(table, f) for f in FEATURES}
    exh = _pool_exh(table)
    payload = {"cost_model_bps": {"fee_per_side_bps": FEE_BPS, "slippage_per_side_bps": SLIP_BPS,
                                  "round_trip_bps": 2 * (FEE_BPS + SLIP_BPS)},
               "price_source": "aggTrades_trade_price (no mid/L2)",
               "days": len(table), "deciles": pooled, "exhaustion": exh}
    (out_dir / "cond_report.json").write_text(json.dumps(payload, indent=2))
    (out_dir / "cond_day.json").write_text(json.dumps(table, indent=2))

    L = ["# Conditional-expectancy report (Dataset A)", "",
         "- Days: %d  Price source: %s" % (len(table), payload["price_source"]),
         "- Cost model: %.1f bps round trip (taker fee %.2f + slippage %.2f per side)"
         % (payload["cost_model_bps"]["round_trip_bps"], FEE_BPS, SLIP_BPS),
         "- Net returns are after this cost model; t-stats are per-day pooled from gross.",
         "", "## Exhaustion (one-sided flow decelerating)", "",
         "| condition | n | net_mean_bps | days |",
         "|---|---|---|---|"]
    for side, v in exh.items():
        if v:
            L.append("| %s | %d | %+.3f | %d |" % (side.upper(), v["n"], v["net_mean_bps"], v["days"]))
        else:
            L.append("| %s | n/a | - | - |" % side.upper())
    L += ["", "## Feature deciles (pooled net mean bps at 15s)", "",
          "| feature | dec | n | gross | net |", "|---|---|---|---|---|"]
    for f in FEATURES:
        for d in sorted(pooled[f]):
            a = pooled[f][d]
            L.append("| %s | %d | %d | %+.3f | %+.3f |" % (f, d, a["n"], a["gross_mean_bps"], a["net_mean_bps"]))
    L += ["", "## Reading the table", "",
          "A condition has predictive value only if its net mean is meaningfully non-zero with a large n.",
          "These tables measure; they do not assume profitability."]
    (out_dir / "cond_report.md").write_text("\n".join(L) + "\n")
    print("cond report: %s" % (out_dir / "cond_report.md"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())