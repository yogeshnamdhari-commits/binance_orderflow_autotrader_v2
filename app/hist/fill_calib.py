"""Empirical passive-fill calibration (Dataset A, authentic aggTrades).

Without L2 history we cannot reconstruct queues, but we CAN measure the
dominant, data-grounded component of passive execution: the probability that
the trade price returns to the reference level within a holding horizon, and
the forward return that is actually captured *conditional on that fill*.

For each event trade i (price p[i]) we interpret a resting passive BUY at the
current price level as filling at the first future trade j with price <= p[i]
(1-tick variant uses p[j] < p[i]). j is found in O(n) with a monotonic stack.
Then:

  touched      = j exists and  t[j] - t[i] in (0, horizon]
  time_to_fill = t[j] - t[i]
  fill_return  = (p[fp(i)] / p[j] - 1) * 1e4    # return from fill price to horizon

The fill-contingent return IS the adverse-selection-corrected edge: it is what
a passive buy at the level actually captures, including the tendency for a fill
to precede further adverse moves. We also report the unconditional forward
return on the same event set for comparison.

`python -m app.hist.fill_calib --symbol BTCUSDT [--start D --end D --days N]`

Outputs data/hist/research/fill_calib.{md,json}.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from .cond import build_day, _forward_ptr, HORIZONS_MS
from .cond_pool import DIRS, condition_trades

ROOT = Path("data") / "hist"


def next_le(p, strict=False):
    """Next index j>i with p[j] <= p[i] (strict: p[j] < p[i]). -1 if none.
    Monotonic increasing stack, right-to-left scan, O(n)."""
    n = len(p)
    out = np.full(n, -1, dtype=np.int64)
    st = []
    for i in range(n - 1, -1, -1):
        while st and (p[st[-1]] >= p[i] if strict else p[st[-1]] > p[i]):
            st.pop()
        out[i] = st[-1] if st else -1
        st.append(i)
    return out


def next_ge(p, strict=False):
    """Next index j>i with p[j] >= p[i] (strict: p[j] > p[i]). -1 if none."""
    n = len(p)
    out = np.full(n, -1, dtype=np.int64)
    st = []
    for i in range(n - 1, -1, -1):
        while st and (p[st[-1]] <= p[i] if strict else p[st[-1]] < p[i]):
            st.pop()
        out[i] = st[-1] if st else -1
        st.append(i)
    return out


def _infer_tick(p):
    d = np.diff(np.unique(p[:200_000]))
    d = d[d > 0]
    return float(np.min(d)) if len(d) else 0.1


class FillSeries:
    def __init__(self, label):
        self.label = label
        self.n = 0
        self.touched_same = 0
        self.touched_1tick = 0
        self.tt_sum = 0.0
        self.ret_sum_same = 0.0
        self.ret_sumsq_same = 0.0
        self.uncond_sum = 0.0

    def add(self, n, touched_same, touched_1tick, tt_sum, ret_sum, ret_sumsq, uncond_sum):
        self.n += n
        self.touched_same += touched_same
        self.touched_1tick += touched_1tick
        self.tt_sum += tt_sum
        self.ret_sum_same += ret_sum
        self.ret_sumsq_same += ret_sumsq
        self.uncond_sum += uncond_sum

    def final(self, maker_rt_bps):
        if self.n == 0:
            return {"label": self.label, "n": 0}
        n = self.n
        p_same = self.touched_same / n
        p_1t = self.touched_1tick / n
        e_fill = (self.ret_sum_same / self.touched_same) if self.touched_same else 0.0
        var = max(self.ret_sumsq_same / self.touched_same - e_fill ** 2, 0.0) if self.touched_same > 1 else 0.0
        sd = float(np.sqrt(var * self.touched_same / max(self.touched_same - 1, 1)))
        se = sd / np.sqrt(self.touched_same) if self.touched_same else 0.0
        tt_mean = (self.tt_sum / self.touched_same) if self.touched_same else 0.0
        uncond = self.uncond_sum / n
        return {"label": self.label, "n": n,
                "p_fill_same_tick": round(p_same, 4),
                "p_fill_1_tick_inside": round(p_1t, 4),
                "e_fill_return_bps": round(e_fill, 3),
                "sd_fill_return_bps": round(sd, 3),
                "se_fill_return_bps": round(se, 3),
                "t_fill_return": round(e_fill / se, 2) if se else 0.0,
                "mean_time_to_fill_ms": round(tt_mean, 1),
                "gross_unconditional_bps": round(uncond, 3),
                "excess_fill_vs_uncond_bps": round(e_fill - uncond, 3),
                "net_after_maker_bps": round(e_fill - maker_rt_bps, 3)}


def _process_day(builder, h, conditions, scans):
    t = builder["t"]
    p = builder["p"]
    fp = _forward_ptr(t, h)
    nle_same, nle_1t, nge_same, nge_1t = scans
    ru = builder["r"][h]
    t_u = t.astype(np.float64)  # for time-to-fill diff
    out = {}
    for feat, dec, dd in conditions:
        rs, idx, _ = condition_trades(builder, feat, dec, h, dd)
        if idx is None or len(idx) == 0:
            out[(feat, dec, dd)] = (0, 0, 0, 0.0, 0.0, 0.0, 0.0)
            continue
        idx = np.asarray(idx)
        cnt = len(idx)
        if dd > 0:  # passive BUY fills when price trades down to our level
            js, j1 = nle_same, nle_1t
        else:       # passive SELL fills when price trades up to our level
            js, j1 = nge_same, nge_1t
        jf = js[idx]
        good = (jf > 0) & (jf < fp[idx]) & np.isfinite(ru[idx])
        touched_same = int(good.sum())
        if touched_same:
            jv = jf[good]
            i = idx[good]
            tt = float(np.sum(t_u[jv] - t_u[i]))
            r = (p[fp[i]] / p[jv] - 1.0) * 1e4 * dd
            rsum = float(np.sum(r))
            rsq = float(np.sum(r * r))
        else:
            tt = rsum = rsq = 0.0
        j1v = j1[idx]
        touched_1t = int(((j1v > 0) & (j1v < fp[idx])).sum())
        uncond = float(np.sum(ru[idx] * 1e4))
        out[(feat, dec, dd)] = (cnt, touched_same, touched_1t, tt, rsum, rsq, uncond)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--days", type=int, default=0, help="sample last N days (0=all)")
    ap.add_argument("--maker-rt", type=float, default=2.0, help="maker round-trip bps")
    args = ap.parse_args(argv)

    root = Path("data") / "hist"
    store = root / "normalized" / args.symbol.upper() / "aggTrades"
    files = sorted(store.glob("*.parquet"))
    if args.start and args.end:
        days = [f.name.split("-aggTrades-")[-1].replace(".parquet", "") for f in files]
        keep = [(f, d) for f, d in zip(files, days) if args.start <= d <= args.end]
        files = [f for f, _ in keep]
    if args.days:
        files = files[-args.days:]
    if not files:
        raise SystemExit("no days available for %s" % args.symbol)
    print("fill calibration over %d day(s)" % len(files), file=sys.stderr)

    conditions = [("delta_5s", dec, dd) for dec in (1, 10) for dd in (1, -1)]
    series = {}
    for c in conditions:
        for h in HORIZONS_MS:
            series[(c, h)] = FillSeries("delta_5s_dec%d_%s" % (c[1], ("long" if c[2] == 1 else "short")))

    for fi, f in enumerate(files):
        try:
            builder = build_day(f, need_span=False)
        except Exception as e:
            print("skip %s: %r" % (f.name, e), file=sys.stderr)
            continue
        p = builder["p"]
        scans = (next_le(p), next_le(p, strict=True), next_ge(p), next_ge(p, strict=True))
        for h in HORIZONS_MS:
            res = _process_day(builder, h, conditions, scans)
            for cond, (cnt, t_s, t_1, tt, rs, rq, u) in res.items():
                series[(cond, h)].add(cnt, t_s, t_1, tt, rs, rq, u)
        if (fi + 1) % 60 == 0:
            print("processed %d/%d days" % (fi + 1, len(files)), file=sys.stderr)

    results = {}
    for (cond, h), s in series.items():
        results["%s@%ds" % (s.label, h // 1000)] = s.final(args.maker_rt)
    payload = {"symbol": args.symbol, "days": len(files), "maker_rt_bps": args.maker_rt,
               "horizons_ms": list(HORIZONS_MS), "results": results}
    out = root / "research"
    out.mkdir(parents=True, exist_ok=True)
    (out / "fill_calib.json").write_text(json.dumps(payload, indent=1))
    (out / "fill_calib.md").write_text(render_md(payload))
    print("fill calibration: %s" % (out / "fill_calib.md"))
    return 0


def render_md(p):
    L = ["# Passive-fill calibration (Dataset A, %d days)" % p["days"],
         "",
         "- Passive BUY (long) fills when a future trade prints AT-or-below our level;",
         "- Passive SELL (short) fills when a future trade prints AT-or-above our level;",
         "- 'fill return' = horizon return measured FROM the fill price (adverse-selection corrected);",
         "- 'unconditional' = horizon return from the event price on the same event set (taker view).",
         "", "## delta_5s conditions x horizon (pooled)", "",
         "| condition | n | P(fill same-tick) | P(fill 1-tick) | mean fill return | unconditional | excess(fill-uncond) | net@maker |",
         "|---|---|---|---|---|---|---|---|"]
    for label, r in p["results"].items():
        L.append("| %s | %d | %.3f | %.3f | %+.2f | %+.2f | %+.2f | %+.2f |" % (
            label, r["n"], r["p_fill_same_tick"], r["p_fill_1_tick_inside"],
            r["e_fill_return_bps"], r["gross_unconditional_bps"],
            r["excess_fill_vs_uncond_bps"], r["net_after_maker_bps"]))
    L += ["", "## Notes", "",
          "- Same-tick fill: first future trade at the reference price (fill at the level).",
          "- 1-tick inside: fill only if a trade prints strictly better than the reference (one tick).",
          "- Time-to-fill mean and standard errors are recorded in the JSON payload.",
          "- Queue position / partial fills are not recoverable from trades-only data;",
          "  the live sampler measures top-of-book depth as the complementary layer.",
          ""]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())