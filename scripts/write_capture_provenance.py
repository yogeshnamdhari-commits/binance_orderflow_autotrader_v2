"""Write per-capture provenance.json (sizes + SHA-256) for V20 audit evidence.

Raw events.jsonl stay local (too large for Git); provenance.json is committed
so the exact bytes used for a backtest are cryptographically identifiable:
capture ID, event count, file sizes, timestamp range, SHA-256, source, schema.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

CAPTURES = [
    "3b8eee35e6d14eb3b38d368c6caf310a",
    "477cf6ae81564e8aa729e79d9cfdc048",
    "9863cf188e1841f3a5738733632f1977",
    "e4153485b12e4ac2b80b4ff81bc08870",
    "ebe81a6484044c5399abd2439d251e3c",
]


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    for cap in CAPTURES:
        d = root / "data" / "captures" / cap
        manifest = json.loads((d / "manifest.json").read_text())
        files = {}
        for name in ("events.jsonl", "snapshot.json", "manifest.json"):
            p = d / name
            if p.is_file():
                files[name] = {
                    "bytes": p.stat().st_size,
                    "sha256": sha256_file(p),
                }
        prov = {
            "capture_id": cap,
            "event_count": manifest.get("event_count"),
            "timestamp_range_ns": [manifest.get("start_ns"), manifest.get("end_ns")],
            "streams": manifest.get("streams"),
            "symbol": manifest.get("symbol"),
            "schema_version": manifest.get("schema_version"),
            "source": "binance-futures",
            "files": files,
        }
        (d / "provenance.json").write_text(json.dumps(prov, indent=2, sort_keys=True) + "\n")
        print(f"{cap}: events sha256={files.get('events.jsonl', {}).get('sha256', 'missing')[:16]}... "
              f"bytes={files.get('events.jsonl', {}).get('bytes')}")


if __name__ == "__main__":
    sys.exit(main())
