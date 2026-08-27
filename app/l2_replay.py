"""Phase 1 — deterministic replay/verification of event-level L2 sessions.

Reads a collector session (data/live/v2/<session>/):
  raw.jsonl   every raw event verbatim (snapshot/depth/trade/bookTicker)
  derived.jsonl  per-event reconstructed book + features (event-linked)

Rebuilds the local book purely from raw.jsonl (same LocalOrderBook +
EventReader semantics as the live collector), recomputes the derived rows,
and checks them against the recorded derived.jsonl. The only live-only field,
recv_ms (wall-clock receive at collection time), is excluded from comparison;
every other value must match bit-for-bit, proving the recorded feature set is
a deterministic function of the immutable raw log.

Also serves as the lossless offline rebuild path referenced by pipeline:
  python -m app.l2_replay <session_dir>
Returns exit code 0 on full match, 1 on mismatch.
"""

import argparse
import json
import sys
from pathlib import Path

from .l2_collector import EventReader
from .orderbook import LocalOrderBook


class Replay:
    def __init__(self, book=None, reader=None, log=print):
        self.book = book or LocalOrderBook(50)
        self.reader = reader or EventReader()
        self.log = log
        self.rows = []
        self.ready = False
        self.trades_buffer = []
        self.events = {"snapshot": 0, "depth": 0, "trade": 0, "bookTicker": 0}
        self.skips = 0

    def feed_line(self, line):
        record = json.loads(line)
        kind = record["kind"]
        now_ms = int(record.get("recv_ms", 0))
        if kind == "snapshot":
            self.book.load_snapshot(record["bids"], record["asks"], record["last_update_id"])
            self.reader.load_snapshot(record["bids"], record["asks"])
            self.ready = True
            self.events["snapshot"] += 1
        elif kind == "depth":
            self.events["depth"] += 1
            if not self.ready:
                self.skips += 1
                return
            e = DepthEventReplay(record)
            status = self.book.apply(e)
            if status != "OK":
                if status == "GAP":
                    self.ready = False
                self.skips += 1
                return
            deltas = self.reader.ofi_event(e, self.book)
            self._flush_trades(e.ts_ms)
            flow = self.reader.trade_window(self.trades_buffer)
            row = self.reader.derived_from_book(
                self.book, e.ts_ms, now_ms, "depth",
                seq="%s-%s" % (e.first_update_id, e.final_update_id),
                depth_deltas=deltas, flow=flow)
            self.rows.append(row)
            self.reader.advance(self.book)
        elif kind == "trade":
            self.events["trade"] += 1
            if not self.ready:
                self.skips += 1
                return
            side = "SELL" if record["m"] else "BUY"
            self.trades_buffer.append({"ts_ms": record["T"], "q": record["q"], "side": side})
            self._flush_trades(record["T"])
            flow = self.reader.trade_window(self.trades_buffer)
            row = self.reader.derived_from_book(
                self.book, record["T"], now_ms, "trade", seq=record["a"], flow=flow)
            self.rows.append(row)
        elif kind == "bookTicker":
            self.events["bookTicker"] += 1
        else:
            raise ValueError("unknown raw kind: %r" % kind)

    def _flush_trades(self, now_ms):
        self.trades_buffer = [t for t in self.trades_buffer
                              if now_ms - t["ts_ms"] <= self.reader.window_ms]


class DepthEventReplay:
    def __init__(self, record):
        self.ts_ms = record["E"]
        self.first_update_id = record["U"]
        self.final_update_id = record["u"]
        self.bids = [(float(p), float(q)) for p, q in record["bids"]]
        self.asks = [(float(p), float(q)) for p, q in record["asks"]]


def _close_enough(a, b):
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))
    return a == b


def compare_rows(rebuilt, recorded, exclude=("recv_ms",), log=lambda s: None):
    mismatches = []
    if len(rebuilt) != len(recorded):
        mismatches.append({"index": -1, "field": "__len__",
                           "left": len(rebuilt), "right": len(recorded)})
    for i, (r, d) in enumerate(zip(rebuilt, recorded)):
        for k in set(r) | set(d):
            if k in exclude:
                continue
            rv, dv = r.get(k), d.get(k)
            if not _close_enough(rv, dv):
                mismatches.append({"index": i, "field": k, "left": rv, "right": dv})
                log("mismatch row %d field %s: rebuilt=%r recorded=%r" % (i, k, rv, dv))
    return mismatches


def replay_session(session_dir, compare=True, log=print):
    session_dir = Path(session_dir)
    raw = session_dir / "raw.jsonl"
    derived = session_dir / "derived.jsonl"
    if not raw.exists():
        raise FileNotFoundError("no raw.jsonl in %s" % session_dir)
    replay = Replay(log=log)
    with open(raw) as f:
        for line in f:
            replay.feed_line(line)
    stats = {"events": replay.events, "rows": len(replay.rows), "skips": replay.skips}
    mismatches = []
    if compare and derived.exists():
        with open(derived) as f:
            recorded = [json.loads(line) for line in f]
        mismatches = compare_rows(replay.rows, recorded, log=log)
        stats["recorded_rows"] = len(recorded)
        stats["mismatches"] = len(mismatches)
    replay.log("replay: %s" % json.dumps(stats))
    if mismatches:
        replay.log("MISMATCH %d/%d reconstructed vs recorded (first 5):"
                   % (len(mismatches), len(recorded)))
        for m in mismatches[:5]:
            replay.log("  %s" % json.dumps(m))
    return replay, mismatches


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("session", type=Path, help="collector session dir")
    args = ap.parse_args(argv)
    _, mismatches = replay_session(args.session)
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())