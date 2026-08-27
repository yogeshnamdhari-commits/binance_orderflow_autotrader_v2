"""Multi-day conditional-expectancy pool (Dataset A).

`python -m app.hist.cond_pool --symbol BTCUSDT [--start D --end D]`

For every available (verified) day we:
- compute regime features: net signed delta (up/down), realized volatility of the
  1s-trade-price path, traded volume proxy;
- thin events to non-overlapping buckets (>= horizon ms apart in time) so exits
  never share the same forward trade;
- accumulate per-day and pooled statistics for every condition x horizon,
  in BOTH the long and short direction (no post-hoc picking of direction).

Outputs (data/hist/research/cond_pooled.{md,json}):
- pooled event statistics (gross and net after the cost model),
- the distribution of per-day means (mean/median/sd/t-tests, % profitable days,
  cumulative equity + max drawdown across ordered days),
- regime breakdown (3x3 quantile buckets of net delta x realized vol),
- cost sensitivity sweep (what round-trip cost kills the pooled gross edge).
"""

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

from .cond import (build_day, condition_trades, excursion_bps, exhaustion_mask,
                   thin_indices, HORIZONS_MS, round_trip_cost_bps, FEE_BPS, SLIP_BPS)

FEATURES = ("delta_5s", "buyshare_5s", "intensity_5s", "accel")
COSTS_BPS = (0.0, 3.0, 6.0, 10.0, 15.0, 20.0)
DIRS = (("long", 1), ("short", -1))


class Series:
    """Running, memory-fixed accumulator for one condition x horizon."""

    def __init__(self, label):
        self.label = label
        self.n = 0
        self.sum = 0.0
        self.sumsq = 0.0
        self.sum_pos = 0.0
        self.sum_neg = 0.0
        self.n_pos = 0.0
        self.mfe_sum = 0.0
        self.mae_sum = 0.0
        self.day_mean = []
        self.day_med = []
        self.day_n = []

    def add_day(self, rs, fav=None, adv=None):
        rs = np.asarray(rs, dtype=np.float64)
        rs = rs[np.isfinite(rs)]
        if len(rs) > 0:
            self.n += len(rs)
            self.sum += float(rs.sum())
            self.sumsq += float((rs ** 2).sum())
            self.sum_pos += float(rs[rs > 0].sum())
            self.sum_neg += float(rs[rs < 0].sum())
            self.n_pos += int((rs > 0).sum())
            if fav is not None and len(fav):
                self.mfe_sum += float(np.sum(fav))
                self.mae_sum += float(np.sum(adv))
            self.day_mean.append(float(rs.mean()))
            self.day_med.append(float(np.median(rs)))
            self.day_n.append(int(len(rs)))
        else:
            self.day_mean.append(0.0)
            self.day_med.append(0.0)
            self.day_n.append(0)

    def final(self, cost_bps):
        if self.n == 0:
            return None
        mean = self.sum / self.n
        var = max(self.sumsq / self.n - mean ** 2, 0.0)
        sd = math.sqrt(var * self.n / max(self.n - 1, 1)) if self.n > 1 else 0.0
        dm = np.asarray(self.day_mean)
        days = len(dm)
        dmed = float(np.median(dm))
        dsd = float(np.std(dm, ddof=1)) if days > 1 else 0.0
        dt = float(np.mean(dm) / (dsd / math.sqrt(days))) if dsd and days > 1 else 0.0
        eq = np.cumsum(dm)
        mdd = float(np.min(eq - np.maximum.accumulate(eq)))
        pf = (self.sum_pos / abs(self.sum_neg)) if self.sum_neg else None
        return {"label": self.label, "n": self.n, "days": days,
                "gross_mean_bps": round(mean, 3),
                "net_mean_bps@%g" % cost_bps: round(mean - cost_bps, 3),
                "median_bps": round(dmed, 3),
                "sd_bps": round(sd, 3),
                "t_stat": round(mean / (sd / math.sqrt(self.n)), 3) if sd else 0.0,
                "sharpe": round(mean / sd * math.sqrt(self.n), 3) if sd else 0.0,
                "hit_rate": round(self.n_pos / self.n * 100, 1),
                "profit_factor": round(pf, 3) if pf is not None else None,
                "mfe_bps": round(self.mfe_sum / self.n, 2),
                "mae_bps": round(self.mae_sum / self.n, 2),
                "day_mean_bps": round(float(np.mean(dm)), 3),
                "day_median_bps": round(dmed, 3),
                "day_sd_bps": round(dsd, 3),
                "day_t": round(dt, 3),
                "pct_profitable_days": round(float(np.mean(dm > 0)) * 100, 1),
                "max_drawdown_bps": round(mdd, 1),
                "per_day_mean_bps": [round(x, 3) for x in self.day_mean],
                "per_day_n": self.day_n}

    def day_means_ns(self):
        return self.day_mean, self.day_n


def _day_features(builder):
    t = builder["t"]
    p = builder["p"]
    q = builder["qv"]
    bin_ms = 1_000
    bid = ((t - t0_ms(t)) // bin_ms).astype(np.int64)
    nb = int(bid[-1]) + 1
    closes = np.full(nb, np.nan)
    closes[bid] = p
    cls = closes[np.isfinite(closes)]
    if len(cls) > 1:
        logr = np.diff(np.log(np.maximum(cls, 1e-9)))
        rv = float(np.std(logr) * 1e4)
    else:
        rv = 0.0
    return {"net_btc": float(np.sum(q)), "rv_bps": rv, "vol_btc": float(np.sum(np.abs(q)))}


def t0_ms(t):
    return int(t[0])


def _conditions(bd, h):
    """Yield (label, thinned_bps_returns, fav_bps, adv_bps)."""
    for feat in FEATURES:
        for dec in (1, 10):
            for dname, dd in DIRS:
                rs, idx, _ = condition_trades(bd, feat, dec, h, dd)
                if rs is None or len(rs) == 0:
                    yield ("%s_dec%d_%s" % (feat, dec, dname), np.array([]), np.array([]), np.array([]))
                else:
                    fav, adv = excursion_bps(bd, idx, h, dd)
                    yield ("%s_dec%d_%s" % (feat, dec, dname), rs, fav, adv)
    buy, sell = exhaustion_mask(bd)
    t = bd["t"]
    r = bd["r"][h]
    for k, m in (("buy_exh", buy), ("sell_exh", sell)):
        for dname, dd in DIRS:
            idx = thin_indices(t, m & np.isfinite(r), h)
            rs = (r[idx] * dd) * 1e4
            fav, adv = excursion_bps(bd, idx, h, dd)
            yield ("%s_%s" % (k, dname), rs, fav, adv)


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
    if not files:
        print("no days to process")
        return 1

    cost = round_trip_cost_bps()
    series = {h: {} for h in HORIZONS_MS}
    day_tags = []
    for f, d in zip(files, days):
        try:
            bd = build_day(f)
        except Exception as e:
            print("ERR %s %r" % (d, e), flush=True)
            continue
        day_tags.append({"day": d, **_day_features(bd)})
        for h in HORIZONS_MS:
            for label, rs, fav, adv in _conditions(bd, h):
                s = series[h].setdefault(label, Series(label))
                s.add_day(rs, fav, adv)
        print("pooled %s" % d, flush=True)

    if not day_tags:
        print("no days processed")
        return 1
    n_days = len(day_tags)
    net_arr = np.array([r["net_btc"] for r in day_tags])
    rv_arr = np.array([r["rv_bps"] for r in day_tags])
    qnet = np.quantile(net_arr, [1 / 3, 2 / 3])
    qrv = np.quantile(rv_arr, [1 / 3, 2 / 3])
    is_up = (net_arr > qnet[1]).tolist()

    payload = {"cost_model_bps": {"fee_per_side_bps": FEE_BPS, "slippage_per_side_bps": SLIP_BPS,
                                  "round_trip_bps": cost},
               "price_source": "aggTrades_trade_price (no mid/L2)",
               "days": n_days, "horizons_ms": list(HORIZONS_MS),
               "regime_buckets_bounds": {"net_btc": [round(float(qnet[0]), 1),
                                                      round(float(qnet[1]), 1)],
                                          "rv_bps": [round(float(qrv[0]), 2),
                                                     round(float(qrv[1]), 2)]}}
    results = {}
    for h in HORIZONS_MS:
        results[h] = {label: s.final(cost) for label, s in series[h].items()}
    payload["results"] = {str(h): results[h] for h in HORIZONS_MS}

    # regime: weighted re-pooling of per-day means by bucket
    labels = sorted(series[HORIZONS_MS[0]].keys())
    short_labs = [lab for lab in labels
                  if (lab.startswith("delta_5s_dec") or lab.startswith("buy_exh")
                      or lab.startswith("sell_exh"))]
    reg = {}
    for i, (up, rv_hi) in enumerate(zip(is_up, (rv_arr > qrv[1]).tolist())):
        bucket = ("up" if up else "dn") + ("_hi" if rv_hi else "_lo")
        b = reg.setdefault(bucket, {lab: [0.0, 0] for lab in short_labs})
        for lab in short_labs:
            dm, dn = series[15_000][lab].day_means_ns()
            b[lab][0] += dm[i] * dn[i]
            b[lab][1] += dn[i]
    regime = {}
    for bucket, agg in reg.items():
        regime[bucket] = {lab: round(agg[lab][0] / agg[lab][1], 3) if agg[lab][1] else None
                          for lab in short_labs}
    payload["regime_gross_mean_bps_15s"] = regime

    # cost sensitivity (pooled gross -> breakeven + % positive days at each cost)
    costsens = {}
    for h in HORIZONS_MS:
        cs = {}
        for lab, s in series[h].items():
            fc = s.final(cost)
            if not fc:
                continue
            dm = s.day_mean
            row = {"gross_mean_bps": fc["gross_mean_bps"],
                   "round_trip_bps": cost}
            for c in COSTS_BPS:
                row["net@%g" % c] = round(fc["gross_mean_bps"] - c, 3)
                row["pct_pos_days@%g" % c] = round(float(np.mean(np.asarray(dm) > c)) * 100, 1)
            cs[lab] = row
        costsens[h] = cs
    payload["cost_sensitivity"] = {str(h): costsens[h] for h in HORIZONS_MS}

    (out_dir / "cond_pooled.json").write_text(json.dumps(payload, indent=2))

    L = ["# Conditional-expectancy pool (Dataset A)", "",
         "- Days: %d  Price source: %s  Horizons: %s"
         % (n_days, payload["price_source"], ", ".join("%ds" % (m // 1000) for m in HORIZONS_MS)),
         "- Cost model: %.1f bps round trip (taker %.2f + slippage %.2f per side)"
         % (cost, FEE_BPS, SLIP_BPS),
         "- Events are thinned to non-overlapping buckets (>= horizon apart in time).",
         "- Every condition is shown in BOTH directions; nothing is picked post-hoc.",
         "- MFE/MAE = mean favorable/adverse excursion over the holding window (bps).",
         "", "## 15s pooled (representative horizon)", "",
         "| condition | n | gross | net | median | t | hit% | pf | mfe | mae | day_mean | day_sd | day_t | pos_days% | mdd |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    key_order = sorted(labels)
    for lab in key_order:
        fc = results[15_000][lab]
        if not fc:
            continue
        L.append("| %s | %d | %+.3f | %+.3f | %+.3f | %+.2f | %.1f | %s | %.2f | %.2f | %+.3f | %.3f | %+.2f | %.1f | %s |"
                 % (lab, fc["n"], fc["gross_mean_bps"], fc["net_mean_bps@%g" % cost],
                    fc["median_bps"] if fc["median_bps"] is not None else float("nan"),
                    fc["t_stat"], fc["hit_rate"],
                    str(fc["profit_factor"]), fc["mfe_bps"], fc["mae_bps"],
                    fc["day_mean_bps"], fc["day_sd_bps"], fc["day_t"],
                    fc["pct_profitable_days"], fc["max_drawdown_bps"]))
    L += ["", "## Horizon comparison (gross mean bps, long direction)", "",
          "| condition | 5s | 15s | 30s | 60s |", "|---|---|---|---|---|"]
    for lab in sorted(labels, key=lambda x: x):
        if not lab.endswith("_long"):
            continue
        cells = []
        for h in HORIZONS_MS:
            fc = results[h][lab]
            cells.append("%+.3f%s" % (fc["gross_mean_bps"], "") if fc else "-")
        L.append("| %s | %s |" % (lab, " | ".join(cells)))
    L += ["", "## Regime breakdown (15s weighted gross bps)", "",
          "| bucket | %s |" % " | ".join(short_labs), "|---|---|"]
    for bucket, rows in regime.items():
        L.append("| %s | %s |" % (bucket, " | ".join(str(rows.get(lab) or "-") for lab in short_labs)))
    (out_dir / "cond_pooled.md").write_text("\n".join(L) + "\n")
    print("pooled report: %s" % (out_dir / "cond_pooled.md"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())