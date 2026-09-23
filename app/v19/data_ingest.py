from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import os
import tarfile
import time
import zipfile
from pathlib import Path
from typing import Iterable, Iterator
from urllib.parse import urlencode

import requests

BINANCE_SIGNED_BASE = "https://api.binance.com/sapi/v1"
BINANCE_VISION_BASE = "https://data.binance.vision/data/futures/um/daily/aggTrades"
MAX_BINANCE_RANGE_MS = 7 * 24 * 60 * 60 * 1000


def split_time_ranges(start_ms: int, end_ms: int, max_range_ms: int = MAX_BINANCE_RANGE_MS) -> list[tuple[int, int]]:
    if start_ms < 0 or end_ms < start_ms:
        raise ValueError("invalid time range")
    if max_range_ms <= 0:
        raise ValueError("max_range_ms must be positive")
    ranges: list[tuple[int, int]] = []
    cursor = start_ms
    while cursor <= end_ms:
        chunk_end = min(cursor + max_range_ms - 1, end_ms)
        ranges.append((cursor, chunk_end))
        cursor = chunk_end + 1
    return ranges


def normalize_binance_depth_row(row: dict[str, str]) -> dict[str, object]:
    return {
        "type": "depth",
        "ts_ms": int(row.get("time", row.get("timestamp", row.get("ts_ms", "0")))),
        "first_update_id": int(row["first_update_id"]) if row.get("first_update_id") else None,
        "last_update_id": int(row["last_update_id"]) if row.get("last_update_id") else None,
        "side": str(row["side"]).lower(),
        "update_type": str(row["update_type"]).lower(),
        "price": float(row["price"]),
        "qty": float(row.get("qty", row.get("quantity", "0"))),
    }


def normalize_binance_trade_row(row: dict[str, str]) -> dict[str, object]:
    maker = row.get("is_buyer_maker", row.get("isBuyerMaker", row.get("buyer_is_maker", "false")))
    return {
        "type": "trade",
        "ts_ms": int(row.get("time", row.get("timestamp", row.get("ts_ms", "0")))),
        "price": float(row["price"]),
        "qty": float(row.get("qty", row.get("quantity", "0"))),
        "buyer_is_maker": str(maker).lower() == "true",
    }


def _signed_params(secret: str, params: dict[str, object]) -> dict[str, object]:
    payload = dict(params)
    payload.setdefault("timestamp", int(time.time() * 1000))
    query = urlencode(payload)
    signature = hmac.new(secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
    payload["signature"] = signature
    return payload


def request_historical_l2_download_id(
    api_key: str,
    api_secret: str,
    symbol: str,
    start_ms: int,
    end_ms: int,
    data_type: str = "T_DEPTH",
    timeout_s: int = 30,
) -> int:
    if not api_key or not api_secret:
        raise ValueError("Binance historical L2 API credentials are required")
    if data_type not in {"T_DEPTH", "S_DEPTH", "T_DEPTH_BACKFILL"}:
        raise ValueError(f"unsupported Binance historical L2 data type: {data_type}")
    params = _signed_params(api_secret, {
        "symbol": symbol,
        "startTime": start_ms,
        "endTime": end_ms,
        "dataType": data_type,
    })
    response = requests.post(
        f"{BINANCE_SIGNED_BASE}/futuresHistDataId",
        params=params,
        headers={"X-MBX-APIKEY": api_key},
        timeout=timeout_s,
    )
    response.raise_for_status()
    payload = response.json()
    if "id" not in payload:
        raise RuntimeError(f"Binance historical L2 request did not return an id: {payload}")
    return int(payload["id"])


def request_historical_l2_download_link(
    api_key: str,
    api_secret: str,
    download_id: int,
    timeout_s: int = 30,
) -> str | None:
    params = _signed_params(api_secret, {"downloadId": download_id})
    response = requests.get(
        f"{BINANCE_SIGNED_BASE}/downloadLink",
        params=params,
        headers={"X-MBX-APIKEY": api_key},
        timeout=timeout_s,
    )
    response.raise_for_status()
    payload = response.json()
    link = payload.get("link")
    if not link or str(link).lower().startswith("link is preparing"):
        return None
    return str(link)


def wait_for_historical_l2_link(
    api_key: str,
    api_secret: str,
    download_id: int,
    poll_seconds: int = 30,
    max_wait_seconds: int = 6 * 60 * 60,
) -> str:
    deadline = time.time() + max_wait_seconds
    while time.time() < deadline:
        link = request_historical_l2_download_link(api_key, api_secret, download_id)
        if link:
            return link
        time.sleep(poll_seconds)
    raise TimeoutError(f"Binance historical L2 download {download_id} was not ready before timeout")


def _iter_csv_members(payload: bytes) -> Iterator[tuple[str, io.TextIOBase]]:
    if payload[:2] == b"PK":
        archive = zipfile.ZipFile(io.BytesIO(payload))
        for name in archive.namelist():
            if name.lower().endswith((".csv", ".csv.gz")):
                raw = archive.read(name)
                if name.lower().endswith(".gz"):
                    import gzip
                    raw = gzip.decompress(raw)
                yield name, io.StringIO(raw.decode("utf-8"))
        return
    if payload[:2] == b"\x1f\x8b":
        import gzip
        payload = gzip.decompress(payload)
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
        for member in archive.getmembers():
            if not member.isfile() or not member.name.lower().endswith(".csv"):
                continue
            extracted = archive.extractfile(member)
            if extracted is not None:
                yield member.name, io.StringIO(extracted.read().decode("utf-8"))


def iter_normalized_depth_csv(payload: bytes) -> Iterator[dict[str, object]]:
    for _, stream in _iter_csv_members(payload):
        reader = csv.DictReader(stream)
        for row in reader:
            yield normalize_binance_depth_row(row)


def iter_normalized_aggtrade_csv(payload: bytes) -> Iterator[dict[str, object]]:
    for _, stream in _iter_csv_members(payload):
        reader = csv.DictReader(stream)
        for row in reader:
            yield normalize_binance_trade_row(row)


def download_bytes(url: str, timeout_s: int = 120) -> bytes:
    response = requests.get(url, timeout=timeout_s)
    response.raise_for_status()
    return response.content


def aggtrade_daily_url(symbol: str, date: str) -> str:
    return f"{BINANCE_VISION_BASE}/{symbol.upper()}/{symbol.upper()}-aggTrades-{date}.zip"


def write_event_rows(rows: Iterable[dict[str, object]], output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
            count += 1
    return count


def require_credentials_from_environment() -> tuple[str, str]:
    key = os.environ.get("BINANCE_FUTURES_API_KEY", "")
    secret = os.environ.get("BINANCE_FUTURES_API_SECRET", "")
    if not key or not secret:
        raise RuntimeError(
            "BINANCE_FUTURES_API_KEY and BINANCE_FUTURES_API_SECRET must be supplied "
            "through the execution environment; never commit or paste them into the repository."
        )
    return key, secret
