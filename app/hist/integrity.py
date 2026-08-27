"""Download + SHA256 integrity verification of Binance public archive files.

Binance publishes a `.CHECKSUM` (SHA256) beside every archive; a file must only
be accepted for analysis if its hash matches.
"""

import hashlib
from pathlib import Path

import requests

from .sources import archive_url, checksum_url, parse_checksum
from .availability import HEADERS


def sha256_of(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def fetch_checksum(symbol, dtype, date, timeout=20, retries=3):
    url = checksum_url(symbol, dtype, date)
    last = None
    for _ in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if r.status_code == 200:
                return parse_checksum(r.text)
            last = ("http_%d" % r.status_code)
        except Exception as e:
            last = repr(e)
    raise RuntimeError("checksum unavailable for %s %s %s: %s" % (symbol, dtype, date, last))


def download_archive(symbol, dtype, date, dest_dir, verify=True, chunk=1 << 20):
    """Download one archive to dest_dir, verifying SHA256. Returns (Path, sha)."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    out_path = dest / ("%s-%s-%s.zip" % (symbol.upper(), dtype, date))
    url = archive_url(symbol, dtype, date)

    if out_path.exists():
        cached = sha256_of(out_path)
        if verify:
            expected_hex, _ = fetch_checksum(symbol, dtype, date)
            if cached == expected_hex:
                return out_path, cached
            out_path.unlink(missing_ok=True)  # corrupted cache -> re-download
        else:
            return out_path, cached

    r = requests.get(url, headers=HEADERS, stream=True, timeout=60)
    r.raise_for_status()
    with open(out_path, "wb") as f:
        for block in r.iter_content(chunk):
            if block:
                f.write(block)

    local = sha256_of(out_path)
    if verify:
        expected_hex, _ = fetch_checksum(symbol, dtype, date)
        if local != expected_hex:
            out_path.unlink(missing_ok=True)
            raise RuntimeError("CHECKSUM MISMATCH %s: expected %s got %s" % (url, expected_hex, local))
    return out_path, local