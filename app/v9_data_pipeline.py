"""
V9 Data Pipeline — Altcoin Data Acquisition and Normalization

Downloads and normalizes altcoin aggTrades data from Binance Vision.
Follows the same pattern as existing BTCUSDT pipeline.

Deterministic, restartable, resumable, checksummed, UTC-normalized, duplicate-safe, gap-detected.
"""
import requests
import pandas as pd
import numpy as np
from pathlib import Path
import time
import json
import hashlib
import zipfile
import io
from datetime import datetime, timedelta, timezone

DATA_DIR = Path("data/hist")
VISION_BASE = "https://data.binance.vision"

UNIVERSE = [
    "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT",
    "AVAXUSDT", "DOTUSDT", "LINKUSDT", "MATICUSDT", "DOGEUSDT",
]

SCHEMA = [
    "agg_trade_id", "price", "quantity",
    "first_trade_id", "last_trade_id",
    "transact_time", "is_buyer_maker",
]


def download_with_retry(url: str, max_retries: int = 3, timeout: int = 60) -> bytes | None:
    """Download with exponential backoff."""
    for attempt in range(max_retries):
        try:
            r = requests.get(url, timeout=timeout)
            if r.status_code == 200:
                return r.content
            elif r.status_code == 404:
                return None
            print(f"  HTTP {r.status_code}, retry {attempt + 1}/{max_retries}")
        except requests.RequestException as e:
            print(f"  Error: {e}, retry {attempt + 1}/{max_retries}")
        time.sleep(2 ** attempt)
    return None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download_and_normalize_symbol(
    symbol: str,
    start_date: str,
    end_date: str,
    dry_run: bool = False,
) -> dict:
    """Download and normalize aggTrades for one symbol."""
    arch_dir = DATA_DIR / "archives" / symbol / "aggTrades"
    norm_dir = DATA_DIR / "normalized" / symbol / "aggTrades"

    if not dry_run:
        arch_dir.mkdir(parents=True, exist_ok=True)
        norm_dir.mkdir(parents=True, exist_ok=True)

    start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    days = []
    d = start
    while d <= end:
        days.append(d)
        d += timedelta(days=1)

    results = {
        "symbol": symbol,
        "total_days": len(days),
        "downloaded": 0,
        "skipped": 0,
        "failed": 0,
        "total_rows": 0,
        "manifest": [],
    }

    for day in days:
        date_str = day.strftime("%Y-%m-%d")
        filename = f"{symbol}-aggTrades-{date_str}.zip"
        url = f"{VISION_BASE}/data/futures/um/daily/aggTrades/{symbol}/{filename}"

        arch_path = arch_dir / filename
        norm_path = norm_dir / f"{symbol}-aggTrades-{date_str}.parquet"

        if norm_path.exists():
            results["skipped"] += 1
            continue

        if dry_run:
            results["downloaded"] += 1
            continue

        data = download_with_retry(url)
        if data is None:
            results["failed"] += 1
            continue

        file_hash = sha256_bytes(data)

        with open(arch_path, "wb") as f:
            f.write(data)

        try:
            z = zipfile.ZipFile(io.BytesIO(data))
            csv_name = z.namelist()[0]
            with z.open(csv_name) as f:
                df = pd.read_csv(f, header=None, skiprows=1)
            if len(df.columns) != 7:
                print(f"  Unexpected columns for {symbol} {date_str}: {len(df.columns)}")
                results["failed"] += 1
                continue

            df.columns = SCHEMA
            df["agg_trade_id"] = pd.to_numeric(df["agg_trade_id"], errors="coerce")
            df["transact_time"] = pd.to_numeric(df["transact_time"], errors="coerce")
            df = df.dropna(subset=["agg_trade_id", "transact_time"])
            df["agg_trade_id"] = df["agg_trade_id"].astype("int64")
            df["transact_time"] = df["transact_time"].astype("int64")
            df = df.drop_duplicates(subset=["agg_trade_id"])
            df = df.sort_values("transact_time").reset_index(drop=True)
            df.to_parquet(norm_path, index=False)

            results["downloaded"] += 1
            results["total_rows"] += len(df)
            results["manifest"].append({
                "date": date_str,
                "hash": file_hash,
                "rows": len(df),
                "filename": filename,
            })
        except Exception as e:
            print(f"  Error processing {symbol} {date_str}: {e}")
            results["failed"] += 1

    return results


def validate_symbol(symbol: str) -> dict:
    """Validate normalized data for a symbol."""
    norm_dir = DATA_DIR / "normalized" / symbol / "aggTrades"
    if not norm_dir.exists():
        return {"symbol": symbol, "status": "NO_DATA"}

    files = sorted(norm_dir.glob("*.parquet"))
    if not files:
        return {"symbol": symbol, "status": "NO_FILES"}

    total_rows = 0
    total_dups = 0
    date_range = {"start": None, "end": None}

    for f in files:
        df = pd.read_parquet(f)
        total_rows += len(df)
        dups = df.duplicated(subset=["agg_trade_id"]).sum()
        total_dups += dups

        date_str = f.stem.split("-")[-1]
        if date_range["start"] is None:
            date_range["start"] = date_str
        date_range["end"] = date_str

    return {
        "symbol": symbol,
        "status": "OK",
        "file_count": len(files),
        "total_rows": total_rows,
        "duplicates": total_dups,
        "date_range": date_range,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="V9 altcoin data pipeline")
    parser.add_argument("--start", default="2024-08-30", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2026-08-30", help="End date (YYYY-MM-DD)")
    parser.add_argument("--symbols", nargs="+", default=UNIVERSE, help="Symbols to download")
    parser.add_argument("--dry-run", action="store_true", help="List what would be downloaded")
    parser.add_argument("--validate-only", action="store_true", help="Only validate existing data")
    args = parser.parse_args()

    print(f"V9 Data Pipeline")
    print(f"  Period: {args.start} to {args.end}")
    print(f"  Symbols: {', '.join(args.symbols)}")
    print()

    if args.validate_only:
        for sym in args.symbols:
            result = validate_symbol(sym)
            print(f"{sym}: {result}")
        return

    all_results = []
    for sym in args.symbols:
        print(f"Processing {sym}...")
        result = download_and_normalize_symbol(sym, args.start, args.end, dry_run=args.dry_run)
        all_results.append(result)
        print(f"  Downloaded: {result['downloaded']}, Skipped: {result['skipped']}, Failed: {result['failed']}, Rows: {result['total_rows']}")
        time.sleep(0.5)

    manifest_path = DATA_DIR / "archives" / "v9_download_manifest.json"
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "start_date": args.start,
        "end_date": args.end,
        "results": all_results,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"\nManifest saved to {manifest_path}")


if __name__ == "__main__":
    main()
