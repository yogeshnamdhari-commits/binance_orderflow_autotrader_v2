"""Untouched out-of-sample test for the frozen delta signal.

PREDECLARED SPLIT (see data/hist/research/oos_PROTOCOL.md, written first):
  TRAIN:      2024-08-16 .. 2025-10-27  (438 days)
  VALIDATION: 2025-10-28 .. 2026-03-22  (146 days)
  OOS:        2026-03-23 .. 2026-08-15  (146 days)  <-- reported ONLY here

The signal definition is frozen: cond_pool.condition_trades over delta_5s
deciles with the same direction mapping, same thinning, same horizons. The
fill/adverse-selection estimator is the monotonic-stack algorithm from
fill_calib.py applied per-day. Nothing is re-fit; OOS days are masked by
calendar date only.

Reports every required metric for OOS and (for context) TRAIN and VALIDATION.

Usage:  python -m app.hist.oos_test --split oos [--split train|validation]
"""

import argparse
import json
from pathlib import Path

import numpy as np

from .cond import build_day, _forward_ptr, excursion_bps, FEE_BPS, SLIP_BPS, HORIZONS_MS, round_trip_cost_bps
from .cond_pool import condition_trades, Series
from .fill_calib import next_le, next_ge

ROOT = Path("data") / "hist"
SPLIT = {
    "train": ("2024-08-16", "2025-10-27"),
    "validation": ("2025-10-28", "2026-03-22"),
    "oos": ("2026-03-23", "2026-08-15"),
}
CONDITIONS = [("delta_5s", 10, "long"), ("delta_5s", 1, "short")]
DEF_COST = round_trip_cost_bps()
COST_SWEEP_BPS = (0.0, 2.0, 4.0, 6.0, 8.0)


class FillOOS:
    def __init__(self, label):
        self.label = label
        self.n = 0
        self.touched = 0
        self.tt_sum = 0.0
        self.ret_sum = 0.0
        self.ret_sumsq = 0.0

    def add(self, n, touched, tt, rs, rss):
        self.n += n
        self.touched += touched
        self.tt_sum += tt
        self.ret_sum += rs
        self.ret_sumsq += rss

    def final(self):
        p_fill = self.touched / self.n if self.n else 0.0
        e_fill = self.ret_sum / self.touched if self.touched else 0.0
        var = max(self.ret_sumsq / self.touched - e_fill ** 2, 0.0) if self.touched > 1 else 0.0
        sd = float(np.sqrt(var * self.touched / max(self.touched - 1, 1)))
        se = sd / np.sqrt(self.touched) if self.touched else 0.0
        return {"label": self.label,
                "p_fill_same_tick": round(p_fill, 4),
                "e_fill_return_bps": round(e_fill, 3),
                "excess_vs_uncond_bps": round(e_fill - self.uncond(), 3),
                "se_bps": round(se, 3),
                "mean_time_to_fill_ms": round(self.tt_sum / self.touched, 1) if self.touched else 0.0}

    def uncond(self):
        return getattr(self, "_uncond", 0.0)


def day_label(f):
    return f.name.split("-aggTrades-")[-1].replace(".parquet", "")


def run_split(name):
    lo, hi = SPLIT[name]
    store = ROOT / "normalized" / "BTCUSDT" / "aggTrades"
    files = [f for f in sorted(store.glob("*.parquet")) if lo <= day_label(f) <= hi]
    if not files:
        raise SystemExit("no days in %s" % (lo, hi))
    print("[%s] %d day(s): %s .. %s" % (name, len(files), lo, hi))

    series = {h: {c: Series("%s_%s" % (c[1], c[2])) for c in CONDITIONS} for h in HORIZONS_MS}
    fills = {h: {c: FillOOS("%s_%s" % (c[1], c[2])) for c in CONDITIONS} for h in HORIZONS_MS}

    for fi, f in enumerate(files):
        try:
            bd = build_day(f, need_span=True)
        except Exception as e:
            print("skip %s: %r" % (f.name, e))
            continue
        t = bd["t"]
        p = bd["p"]
        nle_s, nle_1 = next_le(p), next_le(p, strict=True)
        nge_s, nge_1 = next_ge(p), next_ge(p, strict=True)
        for h in HORIZONS_MS:
            fp = _forward_ptr(t, h)
            for feat, dec, dname in CONDITIONS:
                dd = 1.0 if dname == "long" else -1.0
                rs, idx, _ = condition_trades(bd, feat, dec, h, dd)
                if rs is not None and len(rs) > 0:
                    fav, adv = excursion_bps(bd, idx, h, dd)
                    series[h][(feat, dec, dname)].add_day(rs, fav, adv)
                idx = np.asarray(idx) if idx is not None else np.array([])
                n = len(idx)
                if n == 0:
                    fills[h][(feat, dec, dname)].add(0, 0, 0.0, 0.0, 0.0)
                    continue
                js = nle_s if dd > 0 else nge_s
                jgood = (js[idx] > 0) & (js[idx] < fp[idx])
                touched = int(jgood.sum())
                if touched:
                    jv = js[idx][jgood]
                    ii = idx[jgood]
                    tt = float(np.sum(t.astype(np.float64)[jv] - t.astype(np.float64)[ii]))
                    r = (p[fp[ii]] / p[jv] - 1.0) * 1e4 * dd
                    fills[h][(feat, dec, dname)].add(n, touched, tt, float(np.sum(r)), float(np.sum(r * r)))
                else:
                    fills[h][(feat, dec, dname)].add(n, 0, 0.0, 0.0, 0.0)
        if (fi + 1) % 10 == 0:
            print("  %d/%d days" % (fi + 1, len(files)), flush=True)

    rows = []
    for h in HORIZONS_MS:
        for c in CONDITIONS:
            s = series[h][c]
            if s.n == 0:
                continue
            fin = s.final(DEF_COST)
            fl = fills[h][c].final()
            fl["excess_vs_uncond_bps"] = round(fl["e_fill_return_bps"] - fin["gross_mean_bps"], 3)
            sweep = {}
            for cbps in COST_SWEEP_BPS:
                n2 = s.final(cbps)
                sweep["%.1f" % cbps] = n2["net_mean_bps@%g" % cbps]
            fin.update({"horizon_ms": h, "sweep_net_bps": sweep,
                        "fill": fl, "cost_bps": DEF_COST,
                        "direction": "long" if c[2] == "long" else "short"})
            rows.append(fin)

    payload = {"split": name, "lo": lo, "hi": hi, "days": len(files),
               "signal": "delta_5s decile (frozen)", "cost_bps": DEF_COST,
               "cost_components": {"taker_fee_bps_per_side": FEE_BPS,
                                   "slip_bps_per_side": SLIP_BPS,
                                   "round_trip_bps": DEF_COST},
               "rows": rows}
    out = ROOT / "research"
    out.mkdir(parents=True, exist_ok=True)
    (out / ("oos_%s.json" % name)).write_text(json.dumps(payload, indent=1))
    (out / ("oos_%s.md" % name)).write_text(render_md(payload))
    print("oos_%s -> %s" % (name, out / ("oos_%s.md" % name)))
    return payload


def render_md(p):
    L = ["# OOS report — split %s (%d days: %s .. %s)" % (p["split"], p["days"], p["lo"], p["hi"]),
         "",
         "- Signal: **%s** (frozen, none of this is re-fit)" % p["signal"],
         "- Baseline round-trip cost: %.1f bps" % p["cost_bps"],
         "", "## Per condition x horizon", "",
         "| condition | dir | horizon | n | gross | net | win% | PF | MFE | MAE | Sharpe | MDD | prof-days% |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in p["rows"]:
        key = "net_mean_bps@%g" % p["cost_bps"]
        L.append("| %s | %s | %ds | %d | %+.2f | %+.2f | %.1f | %s | %.2f | %.2f | %.2f | %.2f | %.1f |" % (
            r["label"], r.get("direction", "-"), r["horizon_ms"] // 1000, r["n"],
            r["gross_mean_bps"], r.get(key, 0.0),
            r["hit_rate"], r.get("profit_factor"), r["mfe_bps"], r["mae_bps"],
            r["sharpe"], r["max_drawdown_bps"], r["pct_profitable_days"]))
    L += ["", "## Fill / adverse selection (OOS)", "",
          "| condition | horizon | P(fill same-tick) | E[fill return] | excess vs uncond | mean TTF |",
          "|---|---|---|---|---|---|"]
    for r in p["rows"]:
        fl = r.get("fill", {})
        L.append("| %s | %ds | %.3f | %+.2f | %+.2f | %.0f ms |" % (
            r["label"], r["horizon_ms"] // 1000, fl.get("p_fill_same_tick", 0.0),
            fl.get("e_fill_return_bps", 0.0), fl.get("excess_vs_uncond_bps", 0.0),
            fl.get("mean_time_to_fill_ms", 0.0)))
    L += ["", "## Cost sensitivity (net bps @ 15s)", "",
          "| condition | " + " | ".join("≥%.1f" % c for c in COST_SWEEP_BPS) + " |",
          "|---|---" + "---|" * len(COST_SWEEP_BPS)]
    for r in p["rows"]:
        if r["horizon_ms"] != 15000:
            continue
        sw = r.get("sweep_net_bps", {})
        L.append("| %s | %s |" % (r["label"], " | ".join("%+.2f" % sw.get("%.1f" % c, 0.0) for c in COST_SWEEP_BPS)))
    L += ["", "## Decision (hard-coded)", "",
          "- PASS threshold: OOS net expectancy **> 0** at the baseline cost.",
          "- If net <= 0: STOP live development of this delta signal (documented",
          "  reason required before any re-attempt).",
          "- If net > 0 but margin tiny: remain in research/paper mode.",
          "- Only a materially positive net result proceeds to paper execution,",
          "  real-fill audit, then controlled production.", ""]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="oos", choices=list(SPLIT))
    args = ap.parse_args()
    run_split(args.split)