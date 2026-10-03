#!/usr/bin/env python3
"""Frozen scorer for ORDERFLOW_STATE_TRANSITION-0.1 A-002.

The scorer:
- verifies capture manifest/file SHA-256 fingerprints before reading evidence
- reads reconstructed books only from book_snapshots.jsonl
- reads aggTrade/markPrice from events.jsonl without reconstructing the book
- applies the registered OFI/state/transition rule
- records per-signal execution evidence
- optionally evaluates pooled untouched OOS sessions with the registered
  300-second clock-time block bootstrap

No live trading or account access is used.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
import random
import statistics
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SYMBOL = "BTCUSDT"
HORIZON_MS = 5_000
COOLDOWN_MS = 5_000
OFI_WINDOW_MS = 500
Z_WINDOW_MS = 60_000
DEPTH_LEVELS = 10
REFERENCE_NOTIONAL_USDT = 100.0
TAKER_FEE_RATE = 0.0005
SAFETY_BUFFER_BPS = 2.0

BOOTSTRAP_BLOCK_MS = 300_000
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20261003

REQUIRED_FEEDS = {"depth@100ms", "aggTrade", "markPrice@1s"}


@dataclass(frozen=True)
class Book:
    ts: int
    bids: tuple[tuple[float, float], ...]
    asks: tuple[tuple[float, float], ...]
    update_id: int


@dataclass(frozen=True)
class Trade:
    ts: int
    qty: float
    maker_side: bool


@dataclass(frozen=True)
class Mark:
    ts: int
    funding_rate: float
    funding_time: int


@dataclass(frozen=True)
class Outcome:
    session: int
    signal_time_exchange_ms: int
    book_snapshot_age_ms: int
    entry_snapshot_delay_ms: int
    exit_snapshot_delay_ms: int
    exit_resolution_error_ms: int
    direction: str
    entry_vwap_price: float | None
    exit_vwap_price: float | None
    gross_bps: float | None
    executable_gross_bps: float | None
    fee_bps: float | None
    funding_bps: float | None
    safety_buffer_bps: float
    net_bps: float | None
    adverse_selection_bps: float | None
    book_depth_sufficient: bool
    exclusion_reason: str | None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_manifest(capture_dir: Path) -> dict[str, Any]:
    manifest_path = capture_dir / "manifest.json"
    require(manifest_path.exists(), f"missing manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    require(manifest.get("hypothesis_id") == "ORDERFLOW_STATE_TRANSITION-0.1",
            "wrong hypothesis_id")
    require(manifest.get("symbol") == SYMBOL, "wrong symbol")
    require(manifest.get("contract") == "PERPETUAL", "wrong contract")
    require(manifest.get("economic_model_version") == "A-002",
            "capture is not A-002")
    require(manifest.get("entry_taker_fee_bps") == 5.0,
            "unexpected entry fee")
    require(manifest.get("exit_taker_fee_bps") == 5.0,
            "unexpected exit fee")
    require(manifest.get("round_trip_taker_fee_bps") == 10.0,
            "unexpected round-trip fee")
    require(manifest.get("safety_buffer_bps") == 2.0,
            "unexpected safety buffer")
    require(manifest.get("reference_notional_usdt") == 100.0,
            "unexpected reference notional")
    require(manifest.get("live_order_submission") is False,
            "live order submission must be false")
    require(manifest.get("deployment") == "NO_DEPLOY",
            "deployment must remain NO_DEPLOY")
    require(manifest.get("capture_valid") is True,
            "capture_valid must be true")

    required = set(manifest.get("required_feeds", []))
    require(required == REQUIRED_FEEDS, "required feed set mismatch")

    integrity = manifest.get("integrity", {})
    require(integrity.get("bridged") is True, "book bridge not valid")
    for field in (
        "sequence_gaps",
        "reconnects",
        "transport_errors",
        "malformed_events",
        "missing_feed_events",
    ):
        require(integrity.get(field, 0) == 0, f"invalid integrity field: {field}")

    for name in ("events.jsonl", "book_snapshots.jsonl"):
        meta = manifest.get("files", {}).get(name)
        require(isinstance(meta, dict), f"missing file fingerprint: {name}")
        file_path = capture_dir / name
        require(file_path.exists(), f"missing evidence file: {file_path}")
        actual = sha256_file(file_path)
        require(actual == meta.get("sha256"),
                f"SHA-256 mismatch for {name}: expected {meta.get('sha256')} got {actual}")
        require(file_path.stat().st_size == meta.get("bytes"),
                f"byte-count mismatch for {name}")

    return manifest


def parse_levels(raw: Any) -> tuple[tuple[float, float], ...]:
    out: list[tuple[float, float]] = []
    for pair in raw:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise RuntimeError("malformed book level")
        price, qty = float(pair[0]), float(pair[1])
        if not (math.isfinite(price) and math.isfinite(qty)):
            raise RuntimeError("non-finite book level")
        if price <= 0 or qty < 0:
            raise RuntimeError("invalid book level")
        out.append((price, qty))
    return tuple(out)


def load_books(capture_dir: Path) -> list[Book]:
    books: list[Book] = []
    prev_key: tuple[int, int] | None = None

    with (capture_dir / "book_snapshots.jsonl").open(encoding="utf-8") as fp:
        for line_no, line in enumerate(fp, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            require(row.get("source") == "binance", f"book line {line_no}: bad source")
            require(row.get("symbol") == SYMBOL, f"book line {line_no}: bad symbol")
            require(row.get("synthetic") is False, f"book line {line_no}: synthetic book")
            ts = int(row["timestamp_event_ms"])
            update_id = int(row["last_update_id"])
            key = (ts, update_id)
            if prev_key is not None:
                require(key > prev_key, f"book line {line_no}: non-monotonic event/update order")
            bids = parse_levels(row["bids"])
            asks = parse_levels(row["asks"])
            require(bids and asks, f"book line {line_no}: empty side")
            require(all(bids[i][0] > bids[i + 1][0] for i in range(len(bids) - 1)),
                    f"book line {line_no}: bids not descending")
            require(all(asks[i][0] < asks[i + 1][0] for i in range(len(asks) - 1)),
                    f"book line {line_no}: asks not ascending")
            require(bids[0][0] < asks[0][0], f"book line {line_no}: crossed/locked top book")
            books.append(Book(ts, bids[:DEPTH_LEVELS], asks[:DEPTH_LEVELS], update_id))
            prev_key = key

    require(len(books) >= 2, "need at least two book snapshots")
    return books


def load_events(capture_dir: Path) -> tuple[list[Trade], list[Mark]]:
    trades: list[Trade] = []
    marks: list[Mark] = []

    with (capture_dir / "events.jsonl").open(encoding="utf-8") as fp:
        for line_no, line in enumerate(fp, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            feed = row.get("feed")
            require(row.get("source") == "binance", f"event line {line_no}: bad source")
            require(row.get("symbol") == SYMBOL, f"event line {line_no}: bad symbol")
            require(row.get("synthetic") is False, f"event line {line_no}: synthetic event")
            data = row.get("data", {})
            if feed == "aggTrade":
                ts = int(data["E"])
                qty = float(data["q"])
                require(math.isfinite(qty) and qty > 0, f"event line {line_no}: invalid trade qty")
                trades.append(Trade(ts, qty, bool(data["m"])))
            elif feed == "markPrice":
                ts = int(data["E"])
                rate = float(data["r"])
                funding_time = int(data["T"])
                require(math.isfinite(rate), f"event line {line_no}: invalid funding rate")
                marks.append(Mark(ts, rate, funding_time))

    trades.sort(key=lambda x: x.ts)
    marks.sort(key=lambda x: x.ts)
    return trades, marks


def level_ofi(
    prev_bids: tuple[tuple[float, float], ...],
    prev_asks: tuple[tuple[float, float], ...],
    curr_bids: tuple[tuple[float, float], ...],
    curr_asks: tuple[tuple[float, float], ...],
) -> list[float]:
    """Repository-consistent true multi-level OFI, matching app/v7_true_features.py."""
    prev_bid = dict(prev_bids)
    prev_ask = dict(prev_asks)
    result: list[float] = []

    for i in range(DEPTH_LEVELS):
        bid_change = 0.0
        ask_change = 0.0

        if i < len(curr_bids):
            price, qty = curr_bids[i]
            bid_change = qty - prev_bid.get(price, 0.0)

        if i < len(curr_asks):
            price, qty = curr_asks[i]
            ask_change = qty - prev_ask.get(price, 0.0)

        result.append(bid_change - ask_change)

    return result


def directional_return_bps(side: str, entry: float, exit_: float) -> float:
    if side == "LONG":
        return (exit_ / entry - 1.0) * 10_000.0
    if side == "SHORT":
        return (entry / exit_ - 1.0) * 10_000.0
    raise ValueError(side)


def vwap_for_notional(
    levels: tuple[tuple[float, float], ...],
    notional: float,
) -> tuple[float, float]:
    remaining = notional
    base_qty = 0.0
    spent = 0.0

    for price, qty in levels:
        available = price * qty
        take = min(remaining, available)
        if take > 0:
            q = take / price
            spent += take
            base_qty += q
            remaining -= take
        if remaining <= 1e-12:
            return spent / base_qty, base_qty

    raise ValueError("INSUFFICIENT_DEPTH")


def vwap_for_quantity(
    levels: tuple[tuple[float, float], ...],
    base_qty: float,
) -> tuple[float, float]:
    remaining = base_qty
    filled = 0.0
    notional = 0.0

    for price, qty in levels:
        take_qty = min(remaining, qty)
        if take_qty > 0:
            filled += take_qty
            notional += take_qty * price
            remaining -= take_qty
        if remaining <= 1e-12:
            return notional / filled, filled

    raise ValueError("INSUFFICIENT_DEPTH")


def robust_z(
    current: float,
    prior_sorted: list[float],
) -> float | None:
    if not prior_sorted:
        return None
    med = statistics.median(prior_sorted)
    deviations = sorted(abs(v - med) for v in prior_sorted)
    mad = statistics.median(deviations)
    if mad == 0 or not math.isfinite(mad):
        return None
    return (current - med) / (1.4826 * mad)


def state_direction(zs: tuple[float | None, float | None, float | None], aggressive: float | None) -> str | None:
    z1, z5, z10 = zs
    if aggressive is None or any(z is None for z in zs):
        return None
    values = [float(z1), float(z5), float(z10), float(aggressive)]
    if not all(math.isfinite(v) for v in values):
        return None
    if not (
        math.copysign(1.0, z1) == math.copysign(1.0, z5)
        == math.copysign(1.0, z10)
        == math.copysign(1.0, aggressive)
    ):
        return None
    if min(abs(z1), abs(z5), abs(z10)) < 1.0:
        return None
    if abs(aggressive) < 0.60:
        return None
    return "LONG" if z1 > 0 else "SHORT"


def percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        raise ValueError("empty sample")
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * p
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_values[lo]
    frac = pos - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def bootstrap_clock_blocks(outcomes: list[Outcome]) -> tuple[float, float]:
    scored = [o for o in outcomes if o.net_bps is not None]
    require(scored, "no scored outcomes for bootstrap")

    blocks: dict[int, list[float]] = {}
    for o in scored:
        block_id = o.signal_time_exchange_ms // BOOTSTRAP_BLOCK_MS
        blocks.setdefault(block_id, []).append(float(o.net_bps))

    block_values = list(blocks.values())
    rng = random.Random(BOOTSTRAP_SEED)
    n_blocks = len(block_values)
    samples: list[float] = []

    for _ in range(BOOTSTRAP_RESAMPLES):
        total = 0.0
        count = 0
        for _ in range(n_blocks):
            chosen = block_values[rng.randrange(n_blocks)]
            total += sum(chosen)
            count += len(chosen)
        samples.append(total / count)

    samples.sort()
    return percentile(samples, 0.025), percentile(samples, 0.975)


def median_or_none(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def mean_or_none(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def score_capture(capture_dir: Path) -> tuple[dict[str, Any], list[Outcome]]:
    manifest = load_manifest(capture_dir)
    capture_no = int(manifest["capture"])
    books = load_books(capture_dir)
    trades, marks = load_events(capture_dir)

    trade_idx = 0
    trade_window: deque[tuple[int, float]] = deque()
    trade_sum = 0.0

    # Each entry is (timestamp, OFI1, OFI5, OFI10). Sorted arrays provide
    # deterministic trailing median/MAD windows.
    ofi_windows = [deque(), deque(), deque()]
    ofi_sorted = [[], [], []]

    signal_outcomes: list[Outcome] = []
    states: deque[tuple[int, str | None]] = deque()
    run_direction: str | None = None
    run_length = 0
    last_signal_time: int | None = None

    def add_prior(series: int, ts: int, value: float) -> None:
        ofi_windows[series].append((ts, value))
        bisect.insort(ofi_sorted[series], value)

    def prune_prior(series: int, ts: int) -> None:
        cutoff = ts - Z_WINDOW_MS
        while ofi_windows[series] and ofi_windows[series][0][0] < cutoff:
            _, value = ofi_windows[series].popleft()
            pos = bisect.bisect_left(ofi_sorted[series], value)
            require(pos < len(ofi_sorted[series]), "internal robust-window removal failure")
            ofi_sorted[series].pop(pos)

    def add_trade(ts: int, signed_qty: float) -> None:
        nonlocal trade_sum
        trade_window.append((ts, signed_qty))
        trade_sum += signed_qty

    def prune_trades(ts: int) -> None:
        nonlocal trade_sum
        cutoff = ts - OFI_WINDOW_MS
        while trade_window and trade_window[0][0] < cutoff:
            _, value = trade_window.popleft()
            trade_sum -= value

    trade_events_ts = [t.ts for t in trades]

    for i in range(1, len(books)):
        prev = books[i - 1]
        cur = books[i]
        ts = cur.ts

        while trade_idx < len(trades) and trades[trade_idx].ts <= ts:
            trade = trades[trade_idx]
            signed = -trade.qty if trade.maker_side else trade.qty
            add_trade(trade.ts, signed)
            trade_idx += 1
        prune_trades(ts)

        den = sum(t.qty for t in trades[max(0, trade_idx - 1000):trade_idx])
        # The exact rolling denominator is computed from the active trade window
        # to avoid dependence on an arbitrary event count.
        buy_qty = sum(q for _, q in trade_window if q > 0)
        sell_qty = -sum(q for _, q in trade_window if q < 0)
        total_qty = buy_qty + sell_qty
        aggressive = (
            (buy_qty - sell_qty) / total_qty
            if total_qty > 0
            else None
        )

        levels = level_ofi(prev.bids, prev.asks, cur.bids, cur.asks)
        ofi_values = (
            sum(levels[:1]),
            sum(levels[:5]),
            sum(levels[:10]),
        )

        # Strictly prior robust window: compute z before inserting current OFI.
        for s in range(3):
            prune_prior(s, ts)

        zs = tuple(
            robust_z(ofi_values[s], ofi_sorted[s])
            for s in range(3)
        )

        direction = state_direction(zs, aggressive)

        if direction == run_direction:
            run_length += 1
        elif direction is not None:
            run_direction = direction
            run_length = 1
        else:
            run_direction = None
            run_length = 0

        # State observations from immediately preceding 500ms.
        cutoff = ts - OFI_WINDOW_MS
        while states and states[0][0] < cutoff:
            states.popleft()

        prior_has_not_same = any(
            d != direction for t, d in states if t < ts
        ) if direction is not None else False

        is_transition = (
            direction is not None
            and run_length == 3
            and prior_has_not_same
            and (last_signal_time is None or ts - last_signal_time >= COOLDOWN_MS)
        )

        states.append((ts, direction))

        # Insert current observations after z computation.
        for s in range(3):
            add_prior(s, ts, ofi_values[s])

        if not is_transition:
            continue

        last_signal_time = ts

        # Signal book is the current book snapshot. Entry must be strictly later.
        entry_idx = i + 1
        while entry_idx < len(books) and books[entry_idx].ts <= ts:
            entry_idx += 1

        if entry_idx >= len(books):
            signal_outcomes.append(
                Outcome(
                    capture_no, ts, 0, 0, 0, 0, direction,
                    None, None, None, None, None, None, SAFETY_BUFFER_BPS,
                    None, None, None, False, "MISSING_ENTRY_SNAPSHOT",
                )
            )
            continue

        entry = books[entry_idx]
        target_exit = ts + HORIZON_MS
        exit_idx = entry_idx
        while exit_idx < len(books) and books[exit_idx].ts < target_exit:
            exit_idx += 1

        if exit_idx >= len(books):
            signal_outcomes.append(
                Outcome(
                    capture_no, ts, ts - cur.ts, entry.ts - ts, 0, 0, direction,
                    None, None, None, None, None, None, SAFETY_BUFFER_BPS,
                    None, None, None, False, "MISSING_EXIT_SNAPSHOT",
                )
            )
            continue

        exit_book = books[exit_idx]
        signal_mid = (cur.bids[0][0] + cur.asks[0][0]) / 2.0
        exit_mid = (exit_book.bids[0][0] + exit_book.asks[0][0]) / 2.0
        gross = directional_return_bps(direction, signal_mid, exit_mid)

        try:
            entry_levels = entry.asks if direction == "LONG" else entry.bids
            entry_vwap, base_qty = vwap_for_notional(
                entry_levels, REFERENCE_NOTIONAL_USDT
            )
        except ValueError:
            signal_outcomes.append(
                Outcome(
                    capture_no, ts, ts - cur.ts, entry.ts - ts,
                    exit_book.ts - ts, exit_book.ts - target_exit, direction,
                    None, None, gross, None, None, None, SAFETY_BUFFER_BPS,
                    None, None, None, False, "INSUFFICIENT_DEPTH",
                )
            )
            continue

        try:
            exit_levels = exit_book.bids if direction == "LONG" else exit_book.asks
            exit_vwap, exit_qty = vwap_for_quantity(exit_levels, base_qty)
        except ValueError:
            signal_outcomes.append(
                Outcome(
                    capture_no, ts, ts - cur.ts, entry.ts - ts,
                    exit_book.ts - ts, exit_book.ts - target_exit, direction,
                    entry_vwap, None, gross, None, None, None, SAFETY_BUFFER_BPS,
                    None, None, None, False, "INSUFFICIENT_DEPTH",
                )
            )
            continue

        entry_notional = entry_vwap * base_qty
        exit_notional = exit_vwap * exit_qty
        fee_bps = (TAKER_FEE_RATE * (entry_notional + exit_notional) /
                   REFERENCE_NOTIONAL_USDT * 10_000.0)

        funding_bps = 0.0
        funding_missing = False

        for mark in marks:
            if not (ts < mark.funding_time <= exit_book.ts):
                continue
            if mark.ts > mark.funding_time:
                continue
            # Find the latest mark record before the settlement for this T.
            candidates = [
                m for m in marks
                if m.funding_time == mark.funding_time and m.ts <= mark.funding_time
            ]
            if not candidates:
                funding_missing = True
                break
            latest = candidates[-1]
            rate = latest.funding_rate
            funding_bps += rate * 10_000.0 if direction == "LONG" else -rate * 10_000.0

        if funding_missing:
            signal_outcomes.append(
                Outcome(
                    capture_no, ts, ts - cur.ts, entry.ts - ts,
                    exit_book.ts - ts, exit_book.ts - target_exit, direction,
                    entry_vwap, exit_vwap, gross,
                    directional_return_bps(direction, entry_vwap, exit_vwap),
                    fee_bps, None, SAFETY_BUFFER_BPS, None, None,
                    True, "MISSING_FUNDING_RATE",
                )
            )
            continue

        exec_gross = directional_return_bps(direction, entry_vwap, exit_vwap)
        net = exec_gross - fee_bps - funding_bps - SAFETY_BUFFER_BPS
        adverse = directional_return_bps(direction, entry_vwap, exit_mid)

        signal_outcomes.append(
            Outcome(
                capture_no,
                ts,
                ts - cur.ts,
                entry.ts - ts,
                exit_book.ts - ts,
                exit_book.ts - target_exit,
                direction,
                entry_vwap,
                exit_vwap,
                gross,
                exec_gross,
                fee_bps,
                funding_bps,
                SAFETY_BUFFER_BPS,
                net,
                adverse,
                True,
                None,
            )
        )

    scored = [o for o in signal_outcomes if o.net_bps is not None]
    excluded = [o for o in signal_outcomes if o.net_bps is None]

    summary = {
        "hypothesis_id": "ORDERFLOW_STATE_TRANSITION-0.1",
        "capture": capture_no,
        "capture_role": manifest["capture_role"],
        "capture_valid": manifest["capture_valid"],
        "manifest_verified": True,
        "signal_count": len(signal_outcomes),
        "scored_signal_count": len(scored),
        "excluded_signal_count": len(excluded),
        "exclusion_counts": {
            reason: sum(o.exclusion_reason == reason for o in excluded)
            for reason in sorted({o.exclusion_reason for o in excluded})
        },
        "long_signal_count": sum(o.direction == "LONG" for o in signal_outcomes),
        "short_signal_count": sum(o.direction == "SHORT" for o in signal_outcomes),
        "gross_bps_mean": mean_or_none([o.gross_bps for o in scored if o.gross_bps is not None]),
        "gross_bps_median": median_or_none([o.gross_bps for o in scored if o.gross_bps is not None]),
        "executable_gross_bps_mean": mean_or_none([o.executable_gross_bps for o in scored if o.executable_gross_bps is not None]),
        "executable_gross_bps_median": median_or_none([o.executable_gross_bps for o in scored if o.executable_gross_bps is not None]),
        "fee_bps_mean": mean_or_none([o.fee_bps for o in scored if o.fee_bps is not None]),
        "funding_bps_mean": mean_or_none([o.funding_bps for o in scored if o.funding_bps is not None]),
        "net_bps_mean": mean_or_none([o.net_bps for o in scored if o.net_bps is not None]),
        "net_bps_median": median_or_none([o.net_bps for o in scored if o.net_bps is not None]),
        "adverse_selection_bps_mean": mean_or_none([o.adverse_selection_bps for o in scored if o.adverse_selection_bps is not None]),
        "adverse_selection_bps_median": median_or_none([o.adverse_selection_bps for o in scored if o.adverse_selection_bps is not None]),
        "executable_gross_abs_gt_50_count": sum(
            o.executable_gross_bps is not None and abs(o.executable_gross_bps) > 50.0
            for o in scored
        ),
        "book_snapshot_age_ms_median": median_or_none([o.book_snapshot_age_ms for o in signal_outcomes]),
        "book_snapshot_age_ms_p95": (
            percentile(sorted(o.book_snapshot_age_ms for o in signal_outcomes), 0.95)
            if signal_outcomes else None
        ),
        "entry_snapshot_delay_ms_median": median_or_none([o.entry_snapshot_delay_ms for o in signal_outcomes]),
        "entry_snapshot_delay_ms_p95": (
            percentile(sorted(o.entry_snapshot_delay_ms for o in signal_outcomes), 0.95)
            if signal_outcomes else None
        ),
    }
    return summary, signal_outcomes


def outcome_to_dict(o: Outcome) -> dict[str, Any]:
    return {
        "capture": o.session,
        "signal_time_exchange_ms": o.signal_time_exchange_ms,
        "book_snapshot_age_ms": o.book_snapshot_age_ms,
        "entry_snapshot_delay_ms": o.entry_snapshot_delay_ms,
        "exit_snapshot_delay_ms": o.exit_snapshot_delay_ms,
        "exit_resolution_error_ms": o.exit_resolution_error_ms,
        "direction": o.direction,
        "entry_vwap_price": o.entry_vwap_price,
        "exit_vwap_price": o.exit_vwap_price,
        "gross_bps": o.gross_bps,
        "executable_gross_bps": o.executable_gross_bps,
        "fee_bps": o.fee_bps,
        "funding_bps": o.funding_bps,
        "safety_buffer_bps": o.safety_buffer_bps,
        "net_bps": o.net_bps,
        "adverse_selection_bps": o.adverse_selection_bps,
        "book_depth_sufficient": o.book_depth_sufficient,
        "exclusion_reason": o.exclusion_reason,
    }


def write_outcomes(path: Path, outcomes: list[Outcome]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        for outcome in outcomes:
            fp.write(json.dumps(outcome_to_dict(outcome), sort_keys=True) + "\n")


def write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def score_main(capture_dirs: list[Path], output_root: Path) -> int:
    summaries: list[dict[str, Any]] = []
    all_outcomes: list[Outcome] = []

    for capture_dir in capture_dirs:
        summary, outcomes = score_capture(capture_dir)
        summaries.append(summary)
        all_outcomes.extend(outcomes)

        out_dir = output_root / f"capture_{summary['capture']}"
        write_outcomes(out_dir / "signals.jsonl", outcomes)
        write_summary(out_dir / "summary.json", summary)

    result: dict[str, Any] = {
        "hypothesis_id": "ORDERFLOW_STATE_TRANSITION-0.1",
        "capture_summaries": summaries,
        "economic_decision": "PIPELINE_VALIDATION_ONLY",
        "deployment": "NO_DEPLOY",
    }

    capture_numbers = {int(s["capture"]) for s in summaries}
    if capture_numbers == {2, 3, 4}:
        for s in summaries:
            require(s["capture_role"] == "untouched_oos",
                    f"capture {s['capture']} is not untouched_oos")

        per_session_means = {
            int(s["capture"]): s["net_bps_mean"]
            for s in summaries
        }
        scored_count = sum(int(s["scored_signal_count"]) for s in summaries)

        ci_lo = ci_hi = None
        if scored_count > 0:
            ci_lo, ci_hi = bootstrap_clock_blocks(all_outcomes)

        pooled_mean = mean_or_none(
            [o.net_bps for o in all_outcomes if o.net_bps is not None]
        )

        pass_gate = bool(
            pooled_mean is not None
            and pooled_mean > 0.0
            and ci_lo is not None
            and ci_lo > 0.0
            and all(per_session_means[n] is not None and per_session_means[n] > 0.0
                    for n in (2, 3, 4))
            and all(int(s["scored_signal_count"]) >= 30 for s in summaries)
            and scored_count >= 90
        )

        result.update({
            "economic_decision": "ECONOMIC_CANDIDATE" if pass_gate else "CLOSED_REJECTED",
            "pooled_oos_scored_signal_count": scored_count,
            "pooled_oos_mean_net_bps": pooled_mean,
            "pooled_oos_net_bps_lower_95": ci_lo,
            "pooled_oos_net_bps_upper_95": ci_hi,
            "oos_session_mean_net_bps": per_session_means,
            "oos_min_signal_floor_per_session": 30,
            "oos_min_signal_floor_pooled": 90,
            "bootstrap_block_ms": BOOTSTRAP_BLOCK_MS,
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "gate": {
                "ci_lower_gt_zero": bool(ci_lo is not None and ci_lo > 0.0),
                "session_2_mean_gt_zero": bool(per_session_means[2] is not None and per_session_means[2] > 0),
                "session_3_mean_gt_zero": bool(per_session_means[3] is not None and per_session_means[3] > 0),
                "session_4_mean_gt_zero": bool(per_session_means[4] is not None and per_session_means[4] > 0),
                "session_signal_floors": all(int(s["scored_signal_count"]) >= 30 for s in summaries),
                "pooled_signal_floor": scored_count >= 90,
            },
        })
        if not pass_gate:
            result["deployment"] = "NO_DEPLOY"

    final_path = output_root / "pooled_summary.json"
    write_summary(final_path, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--capture-dir",
        nargs="+",
        type=Path,
        required=True,
        help="one or more capture directories",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help="analysis output directory outside immutable capture evidence",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(score_main(args.capture_dir, args.output_root))
