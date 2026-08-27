"""Audit CLI: `python -m app.hist.audit --symbol BTCUSDT [options]`.

Stage 1 availability probes every date in the window for every public archive
type (no downloads). Stage 2 downloads a sampled subset of aggTrades, verifies
SHA256 checksums, audits quality, normalizes to parquet, and the report stage
writes `data/hist/report.{md,json}`.
"""

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
import csv

from .availability import audit_availability
from .integrity import download_archive
from .quality import audit_file, normalize_aggTrades
from .report import build_report

L2_STATEMENT = (
    "Binance publishes NO tick-by-tick L2 order-book history in the public archive. "
    "`bookDepth` daily files are the depth-at-+/-%-from-mid metric (timestamp, percentage, "
    "depth, notional) and are unusable as L2. The historical L2 facility (T_DEPTH) is access-"
    "granted, serves <7-day request ranges, and can contain gaps; its coverage cannot be "
    "claimed until that access is obtained and audited. No L2 is reconstructed from candles; "
    "periods without authentic L2 are explicitly marked unavailable."
)


def _prev_two_years():
    try:
        today = date.today()
    except Exception:
        today = date(2026, 8, 16)
    return today - timedelta(days=730), today - timedelta(days=1)


def _unzip(zippath, raw_dir):
    raw_dir.mkdir(parents=True, exist_ok=True)
    import zipfile
    with zipfile.ZipFile(zippath) as z:
        names = z.namelist()
        if len(names) != 1:
            raise RuntimeError("unexpected archive contents: %s" % names)
        out = raw_dir / names[0]
        if not out.exists():
            z.extract(names[0], raw_dir)
        return out


def calculate_sample_days(avail, sample_every):
    dates = sorted(d for d, rec in avail["detail"]["aggTrades"].items()
                   if rec.get("status") == 200)
    if not dates:
        return []
    if sample_every <= 0:
        return []
    order = sorted(date.fromisoformat(d) for d in dates)
    picked = order[::sample_every]
    return [d.isoformat() for d in picked]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--sample-every", type=int, default=14,
                    help="integrity/quality sample step in days (0 = availability only)")
    ap.add_argument("--reuse-availability", action="store_true",
                    help="load existing availability.json instead of re-probing")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    if args.start and args.end:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
    else:
        start, end = _prev_two_years()
    if args.out:
        root = Path(args.out)
    else:
        root = Path("data") / "hist"

    # ---- Stage 1: availability (cheap, full range; reusable) ----
    avail_path = root / "availability.json"
    if args.reuse_availability and avail_path.exists():
        avail = json.loads(avail_path.read_text())
        print("stage 1/3  availability loaded from %s" % avail_path, flush=True)
    else:
        print("stage 1/3  availability audit  %s .. %s  (%s, %d types)"
              % (start, end, args.symbol.upper(), 4), flush=True)
        avail = audit_availability(args.symbol, start, end,
                                   types=("aggTrades", "trades", "metrics", "bookDepth"),
                                   workers=args.workers,
                                   results_path=str(avail_path))

    # ---- Stage 2: integrity + quality + normalize on sample days ----
    integrity_rows = []
    if args.sample_every and args.sample_every > 0:
        days = calculate_sample_days(avail, args.sample_every)
        print("stage 2/3  integrity+quality  sample of %d days (step=%d)"
              % (len(days), args.sample_every), flush=True)
        archives = root / "archives" / args.symbol.upper() / "aggTrades"
        rawdir = root / "raw" / args.symbol.upper() / "aggTrades"
        normdir = root / "normalized" / args.symbol.upper() / "aggTrades"
        for i, dayiso in enumerate(days, 1):
            try:
                zpath, sha = download_archive(args.symbol, "aggTrades", dayiso, str(archives))
                csv_path = _unzip(zpath, rawdir)
                q = audit_file("aggTrades", csv_path)
                pre = normdir / ("%s-%s-%s.parquet" % (args.symbol.upper(), "aggTrades", dayiso))
                if pre.exists():
                    norm_path, nrows = pre, None
                else:
                    norm_path, nrows = normalize_aggTrades(csv_path, str(normdir),
                                                           args.symbol, dayiso)
                csv_path.unlink(missing_ok=True)  # parquet is the canonical store
                row = {"date": dayiso, "type": "aggTrades", "checksum": sha[:16],
                       "norm_path": str(norm_path), "norm_rows": nrows}
                row.update(q)
                integrity_rows.append(row)
                print("  [%3d/%3d] %s rows=%d gaps=%s gap_rows=%s ok=%s"
                      % (i, len(days), dayiso, q["rows"], q["id_gaps"],
                         q["id_gap_rows"], sha[:12]), flush=True)
            except Exception as e:
                integrity_rows.append({"date": dayiso, "type": "aggTrades",
                                       "checksum": "ERROR", "error": repr(e)})
                print("  [%3d/%3d] %s ERROR: %r" % (i, len(days), dayiso, e), flush=True)

    # ---- Stage 3: report ----
    print("stage 3/3  report", flush=True)
    build_report(avail, integrity_rows, L2_STATEMENT, str(root))
    print("availability report: %s" % (root / "report.md"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())