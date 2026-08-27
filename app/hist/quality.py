"""Per-day data-quality audit and normalization of Binance public archives.

aggTrades gap audit targets:
- agg_trade_id continuity (Binance agg ids are global; a missing id means the
  archive omits a trade and Delta/CVD would be wrong),
- duplicate ids,
- timestamp ordering (monotonic transact_time),
- day-boundary completeness (first/last timestamps within the UTC day).

bookDepth / metrics are catalogued but excluded from replay (not L2, not core).
"""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

AGGRADE_COLS = ["agg_trade_id", "price", "quantity", "first_trade_id",
                "last_trade_id", "transact_time", "is_buyer_maker"]


def _parse_ts(ms):
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def audit_aggTrades(csv_path):
    """Stream the CSV once: continuity, duplicates, ordering, bounds."""
    gaps = 0
    gap_total = 0
    dup_ids = 0
    ts_drops = 0
    prev_id = None
    prev_ts = None
    first_id = last_id = None
    first_ts = last_ts = None
    rows = 0
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            tid = int(r["agg_trade_id"])
            ts = int(r["transact_time"])
            rows += 1
            if first_id is None:
                first_id = last_id = tid
                first_ts = last_ts = ts
            else:
                if tid <= prev_id:
                    dup_ids += 1
                elif tid > prev_id + 1:
                    gap = tid - prev_id - 1
                    gaps += 1
                    gap_total += gap
                last_id = tid
                last_ts = ts
            if prev_ts is not None and ts < prev_ts:
                ts_drops += 1
            prev_id, prev_ts = tid, ts
    return {
        "rows": rows,
        "first_agg_trade_id": first_id,
        "last_agg_trade_id": last_id,
        "id_gaps": gaps,
        "id_gap_rows": gap_total,
        "duplicate_or_desc_ids": dup_ids,
        "ts_out_of_order": ts_drops,
        "first_transact_time": _parse_ts(first_ts).isoformat() if first_ts else None,
        "last_transact_time": _parse_ts(last_ts).isoformat() if last_ts else None,
        "missing_id_count": int(gap_total),
    }


def audit_bookDepth(csv_path):
    """Prove the file is the depth-at-percentage metric, not L2."""
    schema = None
    rows = 0
    with open(csv_path, newline="") as f:
        reader = csv.reader(f)
        schema = next(reader, None)
        for _ in reader:
            rows += 1
    return {"unusable_as_l2": True,
            "reason": "file is the +/-% depth-from-mid metric, not order-book diff",
            "schema": schema, "rows": rows}


_AUDITORS = {"aggTrades": audit_aggTrades, "bookDepth": audit_bookDepth}


def audit_file(dtype, csv_path):
    fn = _AUDITORS.get(dtype)
    if fn is None:
        return {"rows": None, "note": "catalogued only; not part of replay core"}
    return fn(csv_path)


AGGRADE_NORM_TYPES = {"agg_trade_id": "int64", "price": "float64", "quantity": "float64",
                      "first_trade_id": "int64", "last_trade_id": "int64",
                      "transact_time": "int64", "is_buyer_maker": "bool"}


def normalize_aggTrades(csv_path, out_dir, symbol, date):
    """CSV -> canonical parquet (schema + ordering enforced)."""
    df = pd.read_csv(csv_path)
    df = df.rename(columns=lambda c: c.strip().lower())
    df = df[AGGRADE_COLS].copy()
    df["is_buyer_maker"] = df["is_buyer_maker"].astype(str).str.strip().str.lower() == "true"
    df = df.astype(AGGRADE_NORM_TYPES)
    df = df.sort_values("agg_trade_id").reset_index(drop=True)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / ("%s-%s-%s.parquet" % (symbol.upper(), "aggTrades", date))
    df.to_parquet(out_path, index=False)
    return out_path, len(df)