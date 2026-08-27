"""V3 collector — reuses the authenticated Binance USD-M collector.

V3 does NOT redefine acquisition: depth@100ms, aggTrade and bookTicker are
streamed separately and synchronized into an immutable raw log exactly as in
V2 (gap detection + snapshot recovery). This module only:
  - mirrors existing immutable V2 sessions into data/live/v3 (byte-identical
    raw.jsonl + session.json) so V3 artifacts live under data/live/v3, and
  - optionally runs a fresh collection directly into data/live/v3.

Nothing here downsamples or drops data; the raw log stays the source of truth.
"""

import json
import shutil
from pathlib import Path

from .l2_collector import V2Collector, Config

V3_OUT = Path("data/live/v3")
V2_OUT = Path("data/live/v2")


def mirror_session(src_dir, dst_root=V3_OUT):
    src_dir = Path(src_dir)
    dst = dst_root / src_dir.name
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("raw.jsonl", "session.json"):
        s = src_dir / name
        d = dst / name
        if s.exists() and not d.exists():
            shutil.copyfile(s, d)
    return dst


def mirror_from_v2(v2_root=V2_OUT, dst_root=V3_OUT):
    dst_root = Path(dst_root)
    dst_root.mkdir(parents=True, exist_ok=True)
    sessions = []
    for src in sorted(Path(v2_root).glob("2026*")):
        if not (src / "raw.jsonl").exists():
            continue
        mirror_session(src, dst_root)
        sessions.append(src.name)
    # write the sessions index
    rows = []
    for name in sorted(dst_root.glob("2026*")):
        if (name / "raw.jsonl").exists():
            meta = json.loads((name / "session.json").read_text()) \
                if (name / "session.json").exists() else {}
            rows.append({"session": name.name, "raw_rows": meta.get("raw_rows"),
                         "derived_rows": meta.get("derived_rows"),
                         "window_seconds": meta.get("window_seconds")})
    (dst_root / "sessions.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n")
    return sessions


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--collect-minutes", type=float, default=0.0,
                    help=">0 performs a fresh live collection into data/live/v3")
    ap.add_argument("--out", type=Path, default=V3_OUT)
    a = ap.parse_args(argv)

    mirrored = mirror_from_v2(V2_OUT, a.out)
    print("mirrored %d immutable sessions -> %s" % (len(mirrored), a.out))

    if a.collect_minutes > 0:
        c = V2Collector(cfg=Config(), symbol="btcusdt", out_dir=a.out)
        session = c.run(minutes=a.collect_minutes)
        print("fresh collection complete:", session)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())