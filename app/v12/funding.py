"""V12 funding rate service — fetch and align Binance 8-hour funding rates.

Binance BTCUSDT perpetual funding occurs every 8 hours (00:00, 08:00, 16:00 UTC).
The REST API returns the 8-hour rate as a fraction (e.g. 0.0001 = +0.01% per 8h).

Funding income is a real revenue stream (Rule 13): it must enter net P&L and
must not be assumed zero.
"""
from __future__ import annotations

import json
import time
import urllib.request
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"  # public, no auth
USER_AGENT = "Mozilla/5.0 (compatible; V12-Research/1.0)"


@dataclass(frozen=True)
class FundingPoint:
    funding_time: int  # ms UTC
    funding_rate: float  # 8h rate as fraction


def fetch_funding_rate_history(
    symbol: str = "BTCUSDT",
    start_ms: int | None = None,
    end_ms: int | None = None,
    limit: int = 1000,
    timeout: float = 15.0,
) -> list[FundingPoint]:
    """Fetch historical funding rates from Binance Futures API.

    https://binance-docs.gitbook.io/binance-api-exchange/connecting-to-binance-curl-http-handler/rest-api-reference/futures-market-miscellaneous
    """
    params = {"symbol": symbol.upper(), "limit": str(limit)}
    if start_ms is not None:
        params["startTime"] = str(start_ms)
    if end_ms is not None:
        params["endTime"] = str(end_ms)
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{FUNDING_URL}?{query}"
    last_err: Exception | None = None
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except Exception as exc:
            last_err = exc
            time.sleep(0.5 * (attempt + 1))
    else:
        raise RuntimeError(f"funding rate fetch failed after retries: {last_err}")
    points: list[FundingPoint] = []
    for rec in data:
        points.append(FundingPoint(
            funding_time=int(rec["fundingTime"]),
            funding_rate=float(rec["fundingRate"]),
        ))
    points.sort(key=lambda p: p.funding_time)
    return points


def fetch_current_funding(symbol: str = "BTCUSDT", timeout: float = 10.0) -> dict[str, Any]:
    """Fetch current mark price + funding rate from premiumIndex endpoint."""
    url = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol.upper()}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return {
        "symbol": symbol,
        "mark_price": float(data.get("markPrice", 0)),
        "index_price": float(data.get("indexPrice", 0)),
        "funding_rate": float(data.get("lastFundingRate", 0)),
        "funding_time": int(data.get("time", 0)),
        "next_funding_time": int(data.get("nextFundingTime", 0)),
    }


def get_funding_rate_at(
    points: list[FundingPoint], ts_ms: int
) -> float:
    """Return the 8h funding rate effective at the given timestamp.

    Funding rate at time T is the most recent funding rate whose
    funding_time <= T. Returns 0.0 if no prior funding point exists.
    """
    if not points:
        return 0.0
    times = [p.funding_time for p in points]
    idx = bisect_right(times, ts_ms) - 1
    if idx < 0:
        return 0.0
    return points[idx].funding_rate


def average_funding_rate_during(
    points: list[FundingPoint], start_ms: int, end_ms: int
) -> float:
    """Average 8h funding rate over [start_ms, end_ms].

    Each funding point is weighted by the portion of its 8h window that
    overlaps the holding interval.
    """
    if not points:
        return 0.0
    times = [p.funding_time for p in points]
    idx0 = bisect_right(times, start_ms) - 1
    idx0 = max(idx0, 0)
    total_weighted = 0.0
    total_span = end_ms - start_ms
    if total_span <= 0:
        return get_funding_rate_at(points, start_ms)
    for i in range(idx0, len(points)):
        pt = points[i]
        if pt.funding_time > end_ms:
            break
        period_end = pt.funding_time + 8 * 3600_000
        overlap = min(period_end, end_ms) - max(pt.funding_time, start_ms)
        if overlap > 0:
            total_weighted += pt.funding_rate * overlap
    return total_weighted / total_span


def load_funding_cache(path: str | Path) -> list[FundingPoint]:
    """Load a cached funding rate JSON (list of {fundingTime, fundingRate})."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    points = [
        FundingPoint(funding_time=int(d["fundingTime"]), funding_rate=float(d["fundingRate"]))
        for d in data
    ]
    points.sort(key=lambda p: p.funding_time)
    return points


def fetch_and_cache(
    symbol: str = "BTCUSDT",
    start_ms: int | None = None,
    end_ms: int | None = None,
    cache_path: str | Path | None = None,
    lookback_days: int = 730,
) -> list[FundingPoint]:
    """Fetch historical funding rates, paginated, and optionally cache to JSON."""
    if start_ms is None:
        start_ms = int(time.time() * 1000) - lookback_days * 86400_000
    if end_ms is None:
        end_ms = int(time.time() * 1000)
    all_points: list[FundingPoint] = []
    page_size = 1000
    cur_start = start_ms
    while cur_start <= end_ms:
        try:
            batch = fetch_funding_rate_history(symbol, start_ms=cur_start, end_ms=end_ms, limit=page_size)
        except Exception:
            break
        all_points.extend(batch)
        if not batch:
            break
        if len(batch) < page_size:
            break
        cur_start = batch[-1].funding_time + 1
        time.sleep(0.1)
    all_points.sort(key=lambda p: p.funding_time)
    if cache_path is not None:
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        Path(cache_path).write_text(
            json.dumps(
                [{"fundingTime": p.funding_time, "fundingRate": p.funding_rate} for p in all_points],
                indent=2,
            ),
            encoding="utf-8",
        )
    return all_points
