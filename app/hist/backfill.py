"""Full-window backfill of Binance aggTrades archives -> verified normalized store.

Resumable: days with an existing normalized parquet and a manifest entry are
skipped. Every archive is SHA256-verified against Binance's .CHECKSUM before use.

`python -m app.hist.backfill --symbol BTCUSDT [--workers 6] [--out data/hist]`
"""

import argparse
import json
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

from .availability import audit_availability
from .integrity import download_archive
from .quality import audit_file, normalize_aggTrades


def _unzip(zippath, raw_dir):
    raw_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zippath) as z:
        names = z.namelist()
        if len(names) != 1:
            raise RuntimeError("unexpected archive contents: %s" % names)
        out = raw_dir / names[0]
        if not out.exists():
            z.extract(names[0], raw_dir)
        return out


def _two_years():
    try:
        today = date.today()
    except Exception:
        today = date(2026, 8, 16)
    return today - timedelta(days=730), today - timedelta(days=1)


def load_manifest(path):
    done = {}
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                rec = json.loads(line)
                done[rec["date"]] = rec
            except Exception:
                continue
    return done


def _has_parquet(normdir, symbol, day):
    return (normdir / ("%s-aggTrades-%s.parquet" % (symbol.upper(), day))).exists()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default=None)
    ap.add_argument("--reuse-availability", action="store_true")
    args = ap.parse_args(argv)

    root = Path(args.out) if args.out else Path("data") / "hist"
    if args.start and args.end:
        start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    else:
        start, end = _two_years()

    avail_path = root / "availability.json"
    if args.reuse_availability and avail_path.exists():
        avail = json.loads(avail_path.read_text())
    else:
        avail = audit_availability(args.symbol, start, end,
                                   types=("aggTrades",), workers=32,
                                   results_path=str(avail_path))
    available = sorted(d for d, rec in avail["detail"]["aggTrades"].items()
                       if rec.get("status") == 200)
    if args.start and args.end:
        available = [d for d in available if args.start <= d <= args.end]

    archives = root / "archives" / args.symbol.upper() / "aggTrades"
    rawdir = root / "raw" / args.symbol.upper() / "aggTrades"
    normdir = root / "normalized" / args.symbol.upper() / "aggTrades"
    manifest_path = root / "backfill.jsonl"
    done = load_manifest(manifest_path)

    # Seed manifest rows for days already normalized (audit phase), then skip them.
    seeded = 0
    for d in available:
        if d not in done and _has_parquet(normdir, args.symbol, d):
            rec = {"date": d, "type": "aggTrades", "cached": True}
            with manifest_path.open("a", encoding="utf8") as f:
                f.write(json.dumps(rec, separators=(",", ":")) + "\n")
            done[d] = rec
            seeded += 1

    def _skip(d):
        rec = done.get(d, {})
        if _has_parquet(normdir, args.symbol, d):
            return rec.get("error") is None
        return bool(rec.get("cached"))

    todo = [d for d in available if not _skip(d)]
    print("backfill %s: %d days available, %d already done (+%d seeded), %d to process"
          % (args.symbol.upper(), len(available), len(done) - seeded, seeded, len(todo)),
          flush=True)

    t0 = time.time()
    n_ok = 0
    n_err = 0

    def process(day):
        rec = {"date": day, "type": "aggTrades"}
        try:
            zpath, sha = download_archive(args.symbol, "aggTrades", day, str(archives))
            csv_path = _unzip(zpath, rawdir)
            q = audit_file("aggTrades", csv_path)
            norm_path, nrows = normalize_aggTrades(csv_path, str(normdir),
                                                   args.symbol, day)
            csv_path.unlink(missing_ok=True)
            rec.update({"checksum": sha, "norm_path": str(norm_path),
                        "norm_rows": nrows})
            rec.update({k: q[k] for k in q})
            return day, rec, None
        except Exception as e:
            rec["error"] = repr(e)
            return day, rec, e

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(process, d) for d in todo]
        for fut in as_completed(futures):
            day, rec, err = fut.result()
            with manifest_path.open("a", encoding="utf8") as f:
                f.write(json.dumps(rec, separators=(",", ":")) + "\n")
            if err:
                n_err += 1
                print("  [ERR ] %s  %r" % (day, err), flush=True)
            else:
                n_ok += 1
                q = rec
                print("  [ ok ] %s rows=%s gaps=%s gap_rows=%s sha=%s"
                      % (day, q.get("rows"), q.get("id_gaps"), q.get("id_gap_rows"),
                         q.get("checksum", "")[:12]), flush=True)

    dt = time.time() - t0
    print("backfill complete: ok=%d err=%d in %.0fs (%.1f s/day avg)"
          % (n_ok, n_err, dt, (dt / max(1, n_ok))), flush=True)
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())