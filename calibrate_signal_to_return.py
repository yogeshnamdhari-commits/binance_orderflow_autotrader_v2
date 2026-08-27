#!/usr/bin/env python3
"""
Calibrate signal engine score to expected return in bps.

Replays historical data, computes signal engine output at each update,
and measures future return over a fixed horizon to build a calibration
mapping from signal score to expected return in bps.
"""

import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from app.config import Config
from app.models import DepthEvent, TradeEvent
from app.orderbook import LocalOrderBook
from app.features import OrderFlowEngine
from app.signal import SignalEngine
from app.events import EventDetector


def main():
    # Configuration
    horizon_ms = 15_000  # match decision engine default
    raw_path = Path("data/live/v3/20260818-190746/raw.jsonl")
    if not raw_path.exists():
        print(f"Raw data file not found: {raw_path}")
        return

    # Initialize components (same as in paper validation)
    cfg = Config()
    book = LocalOrderBook(cfg.levels)
    flow = OrderFlowEngine(book)
    detector = EventDetector()
    signal_engine = SignalEngine()

    # We'll need to store mid prices with timestamps to compute future returns
    # We'll keep a queue of (timestamp_ms, mid_price)
    mid_price_history: List[Tuple[int, float]] = []
    # We'll also store signals with their timestamp and side/score
    signals: List[Tuple[int, str, float]] = []  # (timestamp_ms, side, score)

    # Process the raw data file
    print(f"Processing {raw_path}...")
    with open(raw_path) as f:
        for line_num, line in enumerate(f, 1):
            record = json.loads(line)
            kind = record["kind"]
            recv_ms = int(record.get("recv_ms", record.get("ts_ms", record.get("E", 0))))

            if kind == "snapshot":
                book.load_snapshot(record["bids"], record["asks"], record["last_update_id"])
                book.state.synchronized = True
                book.state.last_event_ms = record.get("recv_ms", record["ts_ms"])
                mid = book.state.mid()
                if mid is not None:
                    mid_price_history.append((recv_ms, mid))
            elif kind == "depth":
                e = DepthEvent(
                    ts_ms=record["E"],
                    first_update_id=record["U"],
                    final_update_id=record["u"],
                    bids=[(float(p), float(q)) for p, q in record["bids"]],
                    asks=[(float(p), float(q)) for p, q in record["asks"]]
                )
                status = book.apply(e)
                if status in ("GAP", "STALE"):
                    # Skip invalid events
                    continue
                flow.on_book_event(e)
                mid = book.state.mid()
                if mid is not None:
                    mid_price_history.append((recv_ms, mid))
            elif kind == "trade":
                e = TradeEvent(ts_ms=record["T"], trade_id=record.get("a", record.get("t", 0)),
                               price=float(record["p"]), qty=float(record["q"]),
                               buyer_is_maker=bool(record["m"]))
                flow.on_trade(e)
                # Note: trades do not change the mid price directly, but we can still record mid if needed
                mid = book.state.mid()
                if mid is not None:
                    mid_price_history.append((recv_ms, mid))
            elif kind == "bookTicker":
                # We can update mid from bookTicker if we want, but we already get it from depth/snapshots
                pass
            else:
                continue

            # After processing the update, compute signal if we have enough data
            # We compute signal on every depth update (or every trade?) but to avoid too many signals,
            # we can compute signal every N updates or on every update and then deduplicate by time.
            # For simplicity, we compute signal on every update and then later we will deduplicate by taking the last signal per second.
            f = flow.snapshot(now_ms=recv_ms)
            f.symbol = "BTCUSDT"
            events = detector.detect(f)
            sig = signal_engine.decide(f, events)
            if sig.action in ("BUY", "SELL"):
                signals.append((recv_ms, sig.action, sig.score))

            # Progress indicator
            if line_num % 10000 == 0:
                print(f"  Processed {line_num} lines...")

    print(f"Processed {line_num} lines.")
    print(f"Collected {len(signals)} signals.")

    # Now, for each signal, compute the future return over the horizon
    # We need to find the mid price at signal timestamp and at signal timestamp + horizon_ms
    # We'll sort the mid price history by timestamp (it should already be in order)
    # We'll create a list of timestamps and mids for binary search
    timestamps = [ts for ts, _ in mid_price_history]
    mids = [mid for _, mid in mid_price_history]

    # We'll collect returns by signal score bucket
    # We'll use 10 buckets (0.0-0.1, 0.1-0.2, ..., 0.9-1.0)
    buckets = defaultdict(list)  # key: bucket index (0-9), value: list of returns in bps

    for timestamp_ms, side, score in signals:
        # Find the mid price at or before the signal timestamp
        # We'll use binary search to find the largest timestamp <= signal timestamp
        import bisect
        idx = bisect.bisect_right(timestamps, timestamp_ms) - 1
        if idx < 0:
            continue  # no mid price before signal
        mid_before = mids[idx]

        # Find the mid price at or before signal timestamp + horizon_ms
        future_time = timestamp_ms + horizon_ms
        idx2 = bisect.bisect_right(timestamps, future_time) - 1
        if idx2 < 0:
            continue  # no mid price in the future
        mid_after = mids[idx2]

        # Compute return in bps: (mid_after - mid_before) / mid_before * 10000
        if mid_before == 0:
            continue
        return_bps = (mid_after - mid_before) / mid_before * 10000.0

        # For SELL signals, we expect the return to be negative (price goes down).
        # However, our signal engine's score is positive for SELL as well.
        # We want to calibrate the score to the expected return in the direction of the signal.
        # So for a SELL signal, we expect a negative return, but the score is positive.
        # We can either:
        #   1. Treat SELL signals separately and expect negative returns.
        #   2. For SELL signals, we can take the negative of the return and then expect positive.
        # We'll do option 2 so that we can BUY and SELL signals share the same calibration:
        #   For a BUY signal, we expect positive return -> we use return_bps as is.
        #   For a SELL signal, we expect negative return -> we use -return_bps (so that we expect positive when the price goes down).
        if side == "SELL":
            return_bps = -return_bps

        # Bucket the score
        bucket_idx = int(score * 10)  # 0.0-0.1 -> 0, 0.9-1.0 -> 9 (but note: score=1.0 gives bucket_idx=10, so we clamp)
        if bucket_idx >= 10:
            bucket_idx = 9
        buckets[bucket_idx].append(return_bps)

    # Compute average return for each bucket
    print("\nCalibration results (score bucket -> average expected return in bps):")
    total_return = 0.0
    total_count = 0
    for i in range(10):
        if i in buckets:
            avg = sum(buckets[i]) / len(buckets[i])
            print(f"  Score {i/10:.1f}-{(i+1)/10:.1f}: {avg:+.3f} bps (n={len(buckets[i])})")
            total_return += avg * len(buckets[i])
            total_count += len(buckets[i])
        else:
            print(f"  Score {i/10:.1f}-{(i+1)/10:.1f}: no data")

    if total_count > 0:
        overall_avg = total_return / total_count
        print(f"\nOverall average return: {overall_avg:+.3f} bps (n={total_count})")
    else:
        print("\nNo signals found.")

    # Optionally, we can fit a linear regression: return_bps = a * score + b
    # We'll compute using the bucket midpoints and averages.
    # We'll use the bucket midpoint (i+0.5)/10 as the representative score for the bucket.
    sum_x = 0.0
    sum_y = 0.0
    sum_xx = 0.0
    sum_xy = 0.0
    weight = 0.0
    for i in range(10):
        if i in buckets:
            avg = sum(buckets[i]) / len(buckets[i])
            x = (i + 0.5) / 10.0  # midpoint of the bucket
            y = avg
            w = len(buckets[i])  # weight by number of samples
            sum_x += w * x
            sum_y += w * y
            sum_xx += w * x * x
            sum_xy += w * x * y
            weight += w
    if weight > 0:
        # Linear regression: y = a*x + b
        a = (weight * sum_xy - sum_x * sum_y) / (weight * sum_xx - sum_x * sum_x)
        b = (sum_y - a * sum_x) / weight
        print(f"\nLinear fit: expected_return_bps = {a:+.3f} * score + {b:+.3f}")
        print(f"  (where score is in [0,1])")
    else:
        print("\nNot enough data for linear fit.")


if __name__ == "__main__":
    main()