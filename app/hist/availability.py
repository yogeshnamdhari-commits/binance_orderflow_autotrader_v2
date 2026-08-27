"""Coverage / availability audit of Binance public futures archives.

For every date in [start, end] and every public archive type, probe the archive
URL and record availability. No bytes are downloaded here; integrity is a
separate stage (integrity.py).
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import time
from datetime import date, timedelta
from pathlib import Path

import requests

from .sources import ARCHIVE_TYPES, archive_url, BASE

HEADERS = {"User-Agent": "binance-orderflow-audit/0.1"}

STATUS_LABEL = {
    200: "available",
    404: "missing",
    403: "forbidden",
    429: "rate-limited",
}


def daterange(start, end):
    d = start
    while d <= end:
        yield d.isoformat()
        d += timedelta(days=1)


def probe_one(url, timeout=20, retries=3):
    """Return (status, content_length, error)."""
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, stream=True, timeout=timeout,
                             allow_redirects=True)
            ctype = r.headers.get("Content-Type", "")
            length = int(r.headers.get("Content-Length") or 0)
            r.close()
            return r.status_code, length, None
        except Exception as e:  # network transient
            if attempt == retries - 1:
                return 0, 0, repr(e)
            time.sleep(0.5 * (attempt + 1))
    return 0, 0, "unreachable"


def audit_availability(symbol, start, end, types=ARCHIVE_TYPES, workers=24,
                       results_path=None):
    """Probe every (date, type) combination. Returns dict keyed by type."""
    runs = [(t, d) for t in types for d in daterange(start, end)]
    out = {t: {"dates": {}, "available": 0, "missing": 0, "other": 0,
               "num_dates": len(list(daterange(start, end)))} for t in types}
    started = time.time()
    done = 0

    def probe(task):
        t, d = task
        code, length, err = probe_one(archive_url(symbol, t, d))
        return t, d, code, length, err

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(probe, r) for r in runs]
        for fut in as_completed(futures):
            t, d, code, length, err = fut.result()
            record = {"status": code} if not err else {"status": 0, "error": err}
            if code == 200:
                record["size_bytes"] = length
                out[t]["available"] += 1
            elif code == 404:
                out[t]["missing"] += 1
            else:
                out[t]["other"] += 1
            out[t]["dates"][d] = record
            done += 1
            if done % 100 == 0:
                print("probed %d/%d" % (done, len(runs)), flush=True)

    elapsed = time.time() - started
    for t in types:
        out[t]["probe_seconds"] = round(elapsed, 1)
    payload = {"audit_date_iso": date.today().isoformat(),
               "source": "https://data.binance.vision/data/futures/um/daily (official)",
               "source_is_official": True,
               "reference": "https://github.com/binance/binance-public-data",
               "symbol": symbol.upper(), "start": start.isoformat(), "end": end.isoformat(),
               "types": dict((t, {k: out[t][k] for k in out[t] if k != "dates"}) for t in types),
               "detail": {t: out[t]["dates"] for t in types}}
    if results_path:
        Path(results_path).parent.mkdir(parents=True, exist_ok=True)
        Path(results_path).write_text(json.dumps(payload, indent=2))
    return payload