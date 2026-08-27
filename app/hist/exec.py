"""Execution-cost research over the 730-day pooled conditional results.

`python -m app.hist.exec`

For every candidate condition (mechanically-selected direction) this reports:
- fine cost sweep (0.5..6 bps round trip) of net expectancy and % profitable days,
- exact break-even round-trip cost per condition x horizon,
- which reference execution scenarios (maker/taker, VIP/BNB discounts) fit under it,
- direction independence: winning vs mirrored-losing sides + combined LONG+SHORT
  per-position expectancy, verifying the relationship is symmetric and not drift.

Inputs: data/hist/research/cond_pooled.json (per-day mean/n), cond_bench.json.
Output: data/hist/research/exec_report.{md,json}.
"""

import json
import sys
from pathlib import Path

import numpy as np

from .costmodel import SCENARIOS, describe

HORIZONS = (5_000, 15_000, 30_000, 60_000)
SWEEP = (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0)

CANDIDATES = [
    ("delta_5s_dec10_long", "delta_5s top decile (LONG)"),
    ("delta_5s_dec1_short", "delta_5s bottom decile (SHORT)"),
    ("accel_dec10_long", "acceleration top decile (LONG)"),
    ("accel_dec1_short", "acceleration bottom decile (SHORT)"),
    ("buyshare_5s_dec10_long", "buy-share top decile (LONG)"),
    ("buyshare_5s_dec1_short", "buy-share bottom decile (SHORT)"),
    ("intensity_5s_dec10_long", "intensity top decile (LONG)"),
    ("sell_exh_long", "sell-exhaustion (LONG)"),
    ("buy_exh_short", "buy-exhaustion (SHORT)"),
]


def _va(col, cost):
    dm = np.asarray(col["per_day_mean_bps"])
    return round(float(col["gross_mean_bps"]) - cost, 3), round(float(np.mean(dm > cost)) * 100, 1)


def _combined(colA, colB):
    """Weighted per-position mean across two streams given per-day arrays (nA,nB aligned)."""
    a = np.asarray(colA["per_day_mean_bps"])
    b = np.asarray(colB["per_day_mean_bps"])
    na = np.asarray(colA["per_day_n"])
    nb = np.asarray(colB["per_day_n"])
    w = na + nb
    w = np.where(w > 0, w, 1.0)
    per_day = (na * a + nb * b) / w
    gross = round(float(np.sum(w * per_day) / np.sum(w)), 3)
    return gross, per_day


def main(argv=None):
    root = Path("data") / "hist" / "research"
    pooled = json.loads((root / "cond_pooled.json").read_text())
    cost = pooled["cost_model_bps"]["round_trip_bps"]
    res = pooled["results"]
    scen = describe()["scenarios_round_trip_bps"]

    rows = []
    for lab, disp in CANDIDATES:
        r = {}
        for h in HORIZONS:
            a = res[str(h)][lab]
            if not a:
                r[str(h)] = None
                continue
            gross = a["gross_mean_bps"]
            be = round(gross, 3)
            r[str(h)] = {
                "gross_bps": gross, "break_even_bps": be,
                "net_at_6": round(gross - cost, 3),
                "t_stat": a["t_stat"], "pf": a["profit_factor"],
                "mfe_bps": a["mfe_bps"], "mae_bps": a["mae_bps"],
                "stability_day_t": a["day_t"],
                "viable_maker_passive": be > scen["maker_passive"],
                "viable_taker_full": be > scen["taker_full"],
                "sweep": {c: _va(a, c) for c in SWEEP},
            }
        rows.append({"label": lab, "display": disp, "h": r})

    # direction independence (15s): winning vs losing sides for the flow features
    def _side(lab):
        a = res["15000"][lab]
        return {"gross_bps": a["gross_mean_bps"], "t": a["t_stat"],
                "pos_days": a["pct_profitable_days"], "pf": a["profit_factor"],
                "mfe": a["mfe_bps"], "mae": a["mae_bps"]} if a else None

    sides = {}
    comb = {}
    for f, name in (("delta_5s", "delta"), ("accel", "accel"), ("buyshare_5s", "buy-share")):
        hi = f + "_dec10"
        lo = f + "_dec1"
        sides[name] = {
            "high_long": _side(hi + "_long"), "high_short": _side(hi + "_short"),
            "low_short": _side(lo + "_short"), "low_long": _side(lo + "_long"),
        }
        g, dday = _combined(res["15000"][hi + "_long"], res["15000"][lo + "_short"])
        comb[name] = {"gross_per_position_bps": g,
                      "net_per_position_at6": round(g - cost, 3),
                      "pos_days_pct": round(float(np.mean(dday > 0)) * 100, 1)}

    dg, dday = _combined(res["15000"]["delta_5s_dec10_long"], res["15000"]["delta_5s_dec1_short"])
    combined = comb["delta"]

    payload = {"round_trip_cost_assumption_bps": cost, "scenarios_bps": scen,
               "sweep_bps": list(SWEEP), "candidates": rows,
               "direction_independence_15s": sides, "combined_long_short_15s": combined}
    (root / "exec_report.json").write_text(json.dumps(payload, indent=2))

    L = ["# Execution-cost research (Dataset A, 730 verified days)", "",
         "- Input: pooled conditional results (a 'gross' column is per thinned position).",
         "- Exact break-even = gross (net 0 at that round-trip cost).", ""]
    L += ["## Reference execution scenarios (round-trip bps)", ""]
    for k, v in scen.items():
        L.append("- %s: %.1f" % (k, v))
    L += ["", "## Break-even round-trip cost by condition x horizon", "",
          "| condition | 5s | 15s | 30s | 60s | net@15s@6bps |", "|---|---|---|---|---|---|"]
    for r in rows:
        L.append("| %s | %s | %s | %s | %s | %s |" % (
            r["display"],
            *["%+.3f" % r["h"][str(h)]["break_even_bps"] if r["h"][str(h)] else "-" for h in HORIZONS],
            "%+.3f" % r["h"]["15000"]["net_at_6"] if r["h"]["15000"] else "-"))
    L += ["", "## Cost sweep: net expectancy (bps) at 15s horizon per condition", "",
          "| condition | " + " | ".join("%.1f" % c for c in SWEEP) + " |",
          "| --- | " + " | ".join(["---"] * len(SWEEP)) + " |"]
    for r in rows:
        a = r["h"]["15000"]
        if not a:
            continue
        cells = ["%+.2f" % a["sweep"][c][0] for c in SWEEP]
        L.append("| %s | %s |" % (r["label"], " | ".join(cells)))
    L += ["", "## Direction independence (15s): winning vs mirrored-losing sides", "",
          "| feature | high->LONG | high->SHORT | low->SHORT | low->LONG | combined LONG+SHORT |",
          "|---|---|---|---|---|---|"]
    for name, s in sides.items():
        def fmt(x):
            return "%+.2f (t%+.0f, %s%%)" % (x["gross_bps"], x["t"], int(x["pos_days"])) if x else "-"
        L.append("| %s | %s | %s | %s | %s | %s |" % (
            name, fmt(s["high_long"]), fmt(s["high_short"]),
            fmt(s["low_short"]), fmt(s["low_long"]),
            "gross %+.2f, net@6 %+.2f, pos days %.0f%%" % (
                comb[name]["gross_per_position_bps"], comb[name]["net_per_position_at6"],
                comb[name]["pos_days_pct"])))
    L += ["", "## Verdicts", ""]
    for r in rows:
        a = r["h"]["15000"]
        if not a:
            continue
        v = "viable (maker)" if a["viable_maker_passive"] else "not viable at maker cost"
        if a["viable_taker_full"]:
            v = "viable even at full taker cost"
        L.append("- %s (15s): break-even %.2f bps -> %s" % (r["display"], a["break_even_bps"], v))
    (root / "exec_report.md").write_text("\n".join(L) + "\n")
    print("exec report: %s" % (root / "exec_report.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())