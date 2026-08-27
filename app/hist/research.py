"""Trade-flow research pass over the authentic normalized aggTrades store (Dataset A).

Only checksum-verified, normalized days (data/hist/normalized/*) are consumed.
Outputs:
- per-day trade-flow metrics  -> data/hist/research/day_stats.json
- monthly aggregate summary   -> data/hist/research/month_stats.json
- human-readable table        -> data/hist/research/research_table.md

Metrics are trade-flow only (delta, buy/sell volume, share, trade intensity).
No L2 metrics are derived; L2-dependent rows are explicitly omitted.
"""

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

AGGRADE_COLS = ["agg_trade_id", "price", "quantity", "transact_time", "is_buyer_maker"]


def day_metrics(parquet):
    df = pd.read_parquet(parquet, columns=AGGRADE_COLS)
    maker = df["is_buyer_maker"].astype(bool)
    buy = df.loc[~maker, "quantity"]
    sell = df.loc[maker, "quantity"]
    buy_v = float(buy.sum())
    sell_v = float(sell.sum())
    n = len(df)
    buy_ct = int((~maker).sum())
    span_ms = float(df["transact_time"].max() - df["transact_time"].min())
    total_v = buy_v + sell_v
    return {
        "trades": n,
        "buy_volume_btc": round(buy_v, 6),
        "sell_volume_btc": round(sell_v, 6),
        "total_volume_btc": round(total_v, 6),
        "buy_volume_share": round(buy_v / total_v, 6) if total_v else None,
        "buy_trade_share": round(buy_ct / n, 6) if n else None,
        "delta_btc": round(buy_v - sell_v, 6),
        "cvd_sign": "buyer" if buy_v > sell_v else ("seller" if sell_v > buy_v else "flat"),
        "trade_rate_per_sec": round(n / (span_ms / 1000.0), 3) if span_ms else None,
        "avg_trade_btc": round(total_v / n, 6) if n else None,
    }


def to_month(date_str):
    return date_str[:7]


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
        print("no normalized archives")
        return 1

    day_rows = []
    months = defaultdict(list)
    print("computing metrics for %d days..." % len(files), flush=True)
    for f, d in zip(files, days):
        try:
            m = day_metrics(f)
            m["date"] = d
            day_rows.append(m)
            months[to_month(d)].append(m)
        except Exception as e:
            day_rows.append({"date": d, "error": repr(e)})
            print("  ERR %s %r" % (d, e), flush=True)

    ok = [r for r in day_rows if "error" not in r]
    month_rows = []
    for mlabel in sorted(months):
        ms = months[mlabel]
        mv = sum(r["total_volume_btc"] or 0 for r in ms)
        mb = sum(r["buy_volume_btc"] or 0 for r in ms)
        dd = sum(r["delta_btc"] or 0 for r in ms)
        tt = sum(r["trades"] for r in ms)
        rate = statistics.mean([r["trade_rate_per_sec"] for r in ms if r["trade_rate_per_sec"]])
        month_rows.append({"month": mlabel, "days": len(ms), "trades": tt,
                           "total_volume_btc": round(mv, 2),
                           "buy_volume_btc": round(mb, 2),
                           "buy_share": round(mb / mv, 6) if mv else None,
                           "delta_btc": round(dd, 2),
                           "avg_trade_rate_per_sec": round(rate, 2)})

    (out_dir / "day_stats.json").write_text(json.dumps(day_rows, indent=2))
    (out_dir / "month_stats.json").write_text(json.dumps(month_rows, indent=2))

    lines = ["# Trade-flow research (Dataset A) — %s" % args.symbol.upper(),
             "", "- Days analysed: %d (archives checksum-verified at ingest)" % len(ok),
             "- L2-derived metrics: none (authentic T_DEPTH not in this store)",
             "", "| month | days | trades | vol_btc | buy_share | delta_btc | rate/s |",
             "|---|---|---|---|---|---|---|"]
    for r in month_rows:
        lines.append("| %s | %d | %d | %.0f | %.3f | %+.0f | %.1f |" % (
            r["month"], r["days"], r["trades"], r["total_volume_btc"] / 1e3,
            r["buy_share"] or 0, r["delta_btc"], r["avg_trade_rate_per_sec"]))
    (out_dir / "research_table.md").write_text("\n".join(lines) + "\n")
    print("research table: %s" % (out_dir / "research_table.md"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())