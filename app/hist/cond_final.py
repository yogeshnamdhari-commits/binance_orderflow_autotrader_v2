"""Final consolidated conditional-expectancy report (Dataset A).

`python -m app.hist.cond_final`

Merges cond_pooled.json (730-day pooled condition stats) with cond_bench.json
(unconditional drift baseline) into the Feature x Horizon table:

  Feature x Horizon | Gross edge | Excess vs drift | Net @6bps | PF | Hit% |
  MFE | MAE | Sharpe | Profitable days% | Stability (day_t)

Writes data/hist/research/cond_final.{md,json}.
"""

import json
import sys
from pathlib import Path

HORIZONS = (5_000, 15_000, 30_000, 60_000)
DIRECTION = {"delta_5s_dec1_short": "short", "accel_dec1_short": "short", "buyshare_5s_dec1_short": "short",
             "delta_5s_dec10_long": "long", "accel_dec10_long": "long", "buyshare_5s_dec10_long": "long",
             "intensity_5s_dec10_long": "long", "sell_exh_long": "long", "buy_exh_short": "short"}


def _clean(row):
    return {k: (v if v is not None else "") for k, v in row.items()}


def main(argv=None):
    root = Path("data") / "hist" / "research"
    pooled = json.loads((root / "cond_pooled.json").read_text())
    bench = json.loads((root / "cond_bench.json").read_text())
    results = pooled["results"]
    baseline = {int(h): bench["baseline"][h]["gross_mean_bps"] for h in bench["baseline"]}
    cost = pooled["cost_model_bps"]["round_trip_bps"]

    conds = [
        (("delta_5s", "dec10", "long"), "delta_5s top decile (long)"),
        (("delta_5s", "dec1", "short"), "delta_5s bottom decile (short)"),
        (("accel", "dec10", "long"), "accel top decile (long)"),
        (("accel", "dec1", "short"), "accel bottom decile (short)"),
        (("buyshare_5s", "dec10", "long"), "buyshare top decile (long)"),
        (("buyshare_5s", "dec1", "short"), "buyshare bottom decile (short)"),
        (("intensity_5s", "dec10", "long"), "intensity top decile (long)"),
        (("sell_exh", "long"), "sell-exhaustion (long)"),
        (("buy_exh", "short"), "buy-exhaustion (short)"),
    ]

    output = {"price_source": pooled["price_source"], "days": pooled["days"],
              "horizons_ms": HORIZONS, "cost_round_trip_bps": cost,
              "baseline_gross_bps": {str(h): baseline[h] for h in HORIZONS},
              "rows": []}
    for key, label in conds:
        lab = ("%s_%s_%s" % key) if len(key) == 3 else ("%s_%s" % key)
        row = {"condition": label}
        for h in HORIZONS:
            a = results[str(h)][lab]
            if not a:
                row[str(h)] = None
                continue
            row[str(h)] = {
                "gross_bps": a["gross_mean_bps"],
                "excess_vs_drift_bps": round(a["gross_mean_bps"] - baseline[h], 3),
                "net_bps@%g" % cost: a["net_mean_bps@%g" % cost],
                "pf": a["profit_factor"],
                "hit_pct": a["hit_rate"],
                "mfe_bps": a["mfe_bps"],
                "mae_bps": a["mae_bps"],
                "sharpe": a["sharpe"],
                "pos_days_pct": a["pct_profitable_days"],
                "stability_day_t": a["day_t"],
                "n": a["n"]}
        output["rows"].append(row)

    (root / "cond_final.json").write_text(json.dumps(output, indent=2))

    L = ["# Conditional-expectancy final table (Dataset A, 730 verified days)", "",
         "- Price source: %s  |  %d days  |  horizons: %s"
         % (output["price_source"], output["days"], ", ".join("%ds" % (h // 1000) for h in HORIZONS)),
         "- Cost model: %.1f bps round trip (taker %.2f + slippage %.2f per side); net is after this cost."
         % (cost, pooled["cost_model_bps"]["fee_per_side_bps"], pooled["cost_model_bps"]["slippage_per_side_bps"]),
         "- Events thinned to non-overlapping buckets (>= horizon apart). Both directions measured; the arrows"
         " are the mechanically-tested direction for each condition (nothing picked post-hoc).",
         "- Excess = gross minus unconditional drift baseline at that horizon: %.3f / %.3f / %.3f / %.3f bps."
         % (baseline[5_000], baseline[15_000], baseline[30_000], baseline[60_000]),
         "- Stability = t-stat of the per-day mean distribution across all 730 days (robust persistence).",
         "- NOTE: horizons tested are 5/15/30/60s; 120s was not part of this run.",
         "",
         "## Feature x Horizon", "",
         "| Feature | Horiz | Gross | Excess | Net@%.0f | PF | Hit%% | MFE | MAE | Sharpe | PosDays%% | Stable |"
         % cost,
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for row in output["rows"]:
        for h in HORIZONS:
            a = row[str(h)]
            if not a:
                continue
            L.append("| %s | %3ds | %+.3f | %+.3f | %+.3f | %s | %.1f | %.2f | %.2f | %.1f | %.0f | %+.1f |"
                     % (row["condition"], h // 1000, a["gross_bps"], a["excess_vs_drift_bps"],
                        a["net_bps@%g" % cost], a["pf"] if a["pf"] is not None else "-",
                        a["hit_pct"], a["mfe_bps"], a["mae_bps"], a["sharpe"],
                        a["pos_days_pct"], a["stability_day_t"]))
    (root / "cond_final.md").write_text("\n".join(L) + "\n")
    print("final report: %s" % (root / "cond_final.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())