"""Unconditional forward-return baseline (lean, no features/spans).

`python -m app.hist.cond_bench --symbol BTCUSDT [--start D --end D]`

Reads each verified parquet, computes the mean forward trade-price return at every
horizon over ALL trades (no conditioning, no thinning). This is the market-drift
baseline that any conditional edge must beat. Only the parquet read + two pointer
window is needed; features/excursions are skipped for speed.

Outputs data/hist/research/cond_bench.{json,md}.
"""

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from .cond import HORIZONS_MS, round_trip_cost_bps, FEE_BPS, SLIP_BPS, _forward_ptr

AGGRADE_COLS = ["transact_time", "price", "quantity", "is_buyer_maker"]


class Bench:
    def __init__(self):
        self.n = 0
        self.sum = 0.0
        self.sumsq = 0.0
        self.day_mean = []

    def add_day(self, rs):
        rs = np.asarray(rs, dtype=np.float64)
        rs = rs[np.isfinite(rs)]
        if len(rs) > 0:
            self.n += len(rs)
            self.sum += float(rs.sum())
            self.sumsq += float((rs ** 2).sum())
            self.day_mean.append(float(rs.mean()))
        else:
            self.day_mean.append(0.0)

    def final(self, cost_bps):
        if self.n == 0:
            return None
        mean = self.sum / self.n
        var = max(self.sumsq / self.n - mean ** 2, 0.0)
        sd = math.sqrt(var * self.n / max(self.n - 1, 1)) if self.n > 1 else 0.0
        dm = np.asarray(self.day_mean)
        days = len(dm)
        dsd = float(np.std(dm, ddof=1)) if days > 1 else 0.0
        dt = float(np.mean(dm) / (dsd / math.sqrt(days))) if dsd and days > 1 else 0.0
        eq = np.cumsum(dm)
        mdd = float(np.min(eq - np.maximum.accumulate(eq)))
        return {"n": self.n, "days": days,
                "gross_mean_bps": round(mean, 3),
                "net_mean_bps@%g" % cost_bps: round(mean - cost_bps, 3),
                "sd_bps": round(sd, 3),
                "t_stat": round(mean / (sd / math.sqrt(self.n)), 3) if sd else 0.0,
                "day_mean_bps": round(float(np.mean(dm)), 3),
                "day_sd_bps": round(dsd, 3),
                "day_t": round(dt, 3),
                "pct_positive_days": round(float(np.mean(dm > 0)) * 100, 1),
                "max_drawdown_bps": round(mdd, 1)}


def _lean_returns(parquet):
    df = pd.read_parquet(parquet, columns=AGGRADE_COLS)
    df = df.sort_values("transact_time").reset_index(drop=True)
    t = df["transact_time"].to_numpy(np.int64)
    p = df["price"].to_numpy(np.float64)
    t0 = int(t[0])
    bin_id = ((t - t0) // 1000).astype(np.int64)
    nbins = int(bin_id[-1]) + 1
    bin_open = np.full(nbins, np.nan)
    first = np.flatnonzero(np.concatenate(([True], np.diff(bin_id) != 0)))
    bin_open[np.unique(bin_id)] = p[first]
    out = {}
    for h in HORIZONS_MS:
        fp = _forward_ptr(t, h)
        ok = fp > 0
        j = np.clip(fp, 0, len(t) - 1)
        with np.errstate(divide="ignore", invalid="ignore"):
            out[h] = np.where(ok, p[j] / bin_open[bin_id] - 1.0, np.nan) * 1e4
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    root = Path(args.out) if args.out else Path("data") / "hist"
    store = root / "normalized" / args.symbol.upper() / "aggTrades"
    files = sorted(store.glob("*.parquet"))
    days = [f.name.split("-aggTrades-")[-1].replace(".parquet", "") for f in files]
    if args.start and args.end:
        keep = [(f, d) for f, d in zip(files, days) if args.start <= d <= args.end]
        files, days = zip(*keep) if keep else ((), ())
    if not files:
        print("no days")
        return 1

    cost = round_trip_cost_bps()
    benches = {h: Bench() for h in HORIZONS_MS}
    for f, d in zip(files, days):
        rr = _lean_returns(f)
        for h in HORIZONS_MS:
            benches[h].add_day(rr[h])
        print("bench %s" % d, flush=True)

    final = {str(h): benches[h].final(cost) for h in HORIZONS_MS}
    payload = {"days": len(days),
               "cost_model_bps": {"fee_per_side_bps": FEE_BPS, "slippage_per_side_bps": SLIP_BPS,
                                  "round_trip_bps": cost},
               "price_source": "aggTrades_trade_price (no mid/L2)",
               "baseline": final}
    out_dir = root / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "cond_bench.json").write_text(json.dumps(payload, indent=2))
    L = ["# Unconditional forward-return baseline (Dataset A)", "",
         "- Days: %d  horizons: %s" % (len(days), ", ".join("%ds" % (h // 1000) for h in HORIZONS_MS)),
         "- Mean forward return over ALL trades, trade-price source, no conditioning.",
         "- This is the drift baseline conditional edges must beat.",
         "", "| horizon | n | gross | t | day_mean | day_sd | day_t | pos_days% | mdd |",
         "|---|---|---|---|---|---|---|---|"]
    for h in HORIZONS_MS:
        r = final[str(h)]
        L.append("| %ds | %d | %+.3f | %+.2f | %+.3f | %.3f | %+.2f | %.1f | %s |"
                 % (h // 1000, r["n"], r["gross_mean_bps"], r["t_stat"],
                    r["day_mean_bps"], r["day_sd_bps"], r["day_t"], r["pct_positive_days"],
                    r["max_drawdown_bps"]))
    (out_dir / "cond_bench.md").write_text("\n".join(L) + "\n")
    print("baseline: %s" % (out_dir / "cond_bench.md"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())