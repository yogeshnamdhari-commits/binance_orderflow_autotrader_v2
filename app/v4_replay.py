"""V4 deterministic replay — V3-identical event stream + per-level book depth.

V4 is an EXECUTION-LAYER view of the SAME immutable raw log used by V3:
  - event sequence, ts_ms, session and EVERY feature column are produced by the
    unmodified V3 code path (ReplayV4 subclasses ReplayV3 and only appends
    fields AFTER the base row is built), so the frozen V3 model produces
    byte-identical predictions per event.
  - V4 adds, per depth/trade row, the top-10 bid/ask price-level snapshots so
    the maker fill simulator can reconstruct queue position, fills and adverse
    selection from the L2 event stream.
  - for trade rows it also records the raw trade price/qty/aggressor flag
    (required to attribute queue consumption to the aggressive side).

No market parameter is estimated here; this is pure function of the immutable
raw logs (recv_ms excluded from comparisons, exactly like V3).
"""

import json
from pathlib import Path

from .v3_replay import ReplayV3

LEVELS_COUNT = 10


class ReplayV4(ReplayV3):
    def __init__(self, book=None, log=print):
        super().__init__(book=book, log=log)
        self._trade_info = None

    def feed_line(self, line):
        rec = json.loads(line)
        if rec.get("kind") == "trade":
            self._trade_info = {"price": float(rec["p"]), "qty": float(rec["q"]),
                                "maker": bool(rec.get("m")), "T": int(rec["T"])}
        else:
            self._trade_info = None
        super().feed_line(line)

    def _row(self, ts_ms, recv_ms, kind, seq, ofi, cancel, flow):
        row = super()._row(ts_ms, recv_ms, kind, seq, ofi, cancel, flow)
        bids, asks = self.book.level_quantities(LEVELS_COUNT)
        row["levels_bid"] = [[float(p), float(q)] for p, q in bids]
        row["levels_ask"] = [[float(p), float(q)] for p, q in asks]
        if kind == "trade":
            ti = self._trade_info or {}
            row["trade_price"] = ti.get("price")
            row["trade_qty"] = ti.get("qty")
            row["trade_maker"] = ti.get("maker")
        else:
            row["trade_price"] = None
            row["trade_qty"] = None
            row["trade_maker"] = None
        return row


def replay_session(session_dir, write=True, out_dir=None, log=print):
    session_dir = Path(session_dir)
    raw = session_dir / "raw.jsonl"
    if not raw.exists():
        raise FileNotFoundError("no raw.jsonl in %s" % session_dir)
    rp = ReplayV4(log=log)
    with open(raw) as f:
        for line in f:
            line = line.strip()
            if line:
                rp.feed_line(line)
    if write:
        out_dir = Path(out_dir) if out_dir else session_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / "derived_v4.jsonl"
        with open(out, "w") as f:
            for row in rp.rows:
                f.write(json.dumps(row) + "\n")
        log("v4 replay %s: %d rows, %d skips" % (session_dir.name,
                                                 len(rp.rows), rp.skips))
    return rp


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("session_dirs", nargs="+", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    total = 0
    for sd in a.session_dirs:
        rp = replay_session(sd, write=True, out_dir=a.out)
        total += len(rp.rows)
    print("total v4 rows:", total)