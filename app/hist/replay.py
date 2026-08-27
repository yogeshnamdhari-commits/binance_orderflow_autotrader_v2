"""Replay normalized authentic archives through the order-flow engine.

`python -m app.hist.replay --symbol BTCUSDT --start 2026-07-03 --end 2026-07-17`

Replays only days whose normalized archives exist and are checksum-verified
(see `app.hist.audit`). Trade-driven features are computed; L2-derived features
are recorded as unavailable, never synthesized.
"""

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from ..config import Config
from ..orderbook import LocalOrderBook
from ..features import OrderFlowEngine
from ..events import EventDetector
from ..signal import SignalEngine
from ..journal import Journal
from ..replay import EventReplay


def _normalized_days(symbol, root):
    d = Path(root) / "normalized" / symbol.upper() / "aggTrades"
    if not d.exists():
        return []
    return sorted(p.name.split("-aggTrades-")[-1].replace(".parquet", "") for p in d.glob("*.parquet"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    root = Path(args.out) if args.out else Path("data") / "hist"
    days = _normalized_days(args.symbol, root)
    if not days:
        print("no normalized archives found under %s/normalized/%s" % (root, args.symbol.upper()))
        return 1
    if args.start and args.end:
        span = [d for d in days if args.start <= d <= args.end]
    else:
        span = days[-1:] if not args.start else [d for d in days if d >= args.start]
        if args.end:
            span = [d for d in span if d <= args.end]
    if not span:
        print("no replayable days in range")
        return 1

    cfg = Config()
    book = LocalOrderBook(cfg.levels)
    flow = OrderFlowEngine(book)
    replay = EventReplay(book, flow, EventDetector(), SignalEngine(),
                         Journal(str(Path(root) / "replay" / "journal.jsonl")))

    print("%-12s %10s %8s %8s %8s %12s" % ("date", "trades", "buys", "sells", "buy%", "cvd_end"))
    for day in span:
        p = Path(root) / "normalized" / args.symbol.upper() / "aggTrades" / \
            ("%s-aggTrades-%s.parquet" % (args.symbol.upper(), day))
        stats = replay.run_aggTrades_parquet(p, "aggTrades:%s:%s" % (args.symbol.upper(), day))
        buy_pct = 100.0 * stats["buys"] / stats["trades"] if stats["trades"] else 0.0
        print("%-12s %10d %8d %8d %8.1f %12.2f" % (
            day, stats["trades"], stats["buys"], stats["sells"], buy_pct, stats["cvd_end"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())