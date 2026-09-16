"""Authentic-data V20 market-making performance certification.

The runner captures public Binance BTCUSDT depth/trade data locally, performs a
causal chronological replay, selects candidate microstructure parameters only
on the first half of the capture, and certifies them on the untouched second
half. No order placement and no synthetic market data are used.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.mm.book import L2Snapshot, L2Update, OrderBook
from app.mm.config import V20Config
from app.mm.event_backtest import EventBacktestResult, run_event_backtest
from app.mm.execution_replay import TradeEvent
from scripts.v20_event_backtest_capture import load_events, load_snapshot


def _load_config(path: Path, maker_fee_bps: float) -> V20Config:
    config, _ = V20Config.load_authoritative(str(path))
    return replace(config, maker_fee_bps=maker_fee_bps, live_order_submission=False)


def _event_timestamp_ns(depth: list[L2Update], trades: list[TradeEvent]) -> list[int]:
    return [e.timestamp_ns for e in depth] + [e.timestamp_ns for e in trades]


def _split_events(
    snapshot: L2Snapshot,
    depth: list[L2Update],
    trades: list[TradeEvent],
) -> tuple[L2Snapshot, list[L2Update], list[TradeEvent], L2Snapshot, list[L2Update], list[TradeEvent]]:
    timestamps = sorted(_event_timestamp_ns(depth, trades))
    if len(timestamps) < 2000:
        raise ValueError(f"insufficient events for certification: {len(timestamps)}")
    split_ts = timestamps[len(timestamps) // 2]

    train_depth = [e for e in depth if e.timestamp_ns <= split_ts]
    train_trades = [e for e in trades if e.timestamp_ns <= split_ts]
    valid_depth = [e for e in depth if e.timestamp_ns > split_ts]
    valid_trades = [e for e in trades if e.timestamp_ns > split_ts]
    if len(train_depth) < 100 or len(valid_depth) < 100:
        raise ValueError("train/validation depth split is too small")
    if not valid_trades:
        raise ValueError("validation contains no trades")

    book = OrderBook.from_snapshot(snapshot)
    for event in train_depth:
        book.apply_update(event)

    train_snapshot = snapshot
    validation_snapshot = L2Snapshot(
        timestamp_ns=book.timestamp_ns,
        last_update_id=book.last_update_id,
        bids=book.get_depth("bid", levels=1000),
        asks=book.get_depth("ask", levels=1000),
    )
    return train_snapshot, train_depth, train_trades, validation_snapshot, valid_depth, valid_trades


def _score(result: EventBacktestResult) -> tuple[float, int]:
    # Training objective: reward net P&L while penalizing toxic execution.
    objective = result.net_pnl_usd - 0.05 * abs(result.avg_adverse_selection_bps) * max(1.0, result.filled_qty)
    return objective, result.fills


def _candidate_grid(base: V20Config) -> list[V20Config]:
    candidates: list[V20Config] = []
    for half_spread in (2.0, 2.5, 3.0, 3.5):
        for imbalance in (0.55, 0.65, 0.75):
            for flow in (0.55, 0.65, 0.75):
                for skew in (0.5, 1.0, 1.5):
                    candidates.append(
                        replace(
                            base,
                            base_half_spread_bps=half_spread,
                            max_half_spread_bps=max(half_spread + 1.0, base.max_half_spread_bps),
                            toxicity_filter_enabled=True,
                            toxicity_imbalance_threshold=imbalance,
                            toxicity_flow_threshold=flow,
                            microprice_skew_bps=skew,
                            live_order_submission=False,
                        )
                    )
    return candidates


def _run(result_cfg: V20Config, snapshot: L2Snapshot, depth: list[L2Update], trades: list[TradeEvent]) -> EventBacktestResult:
    return run_event_backtest(snapshot, depth, trades, result_cfg)


def _bucket_results(
    snapshot: L2Snapshot,
    depth: list[L2Update],
    trades: list[TradeEvent],
    config: V20Config,
) -> list[EventBacktestResult]:
    timestamps = sorted(_event_timestamp_ns(depth, trades))
    if len(timestamps) < 400:
        return []
    boundaries = [timestamps[(len(timestamps) * i) // 4] for i in range(1, 4)]
    results: list[EventBacktestResult] = []
    current_snapshot = snapshot
    current_depth = depth
    current_trades = trades
    # Evaluate sequential quartiles with a reconstructed book snapshot so each
    # bucket is causally self-contained.
    for idx in range(4):
        low = timestamps[(len(timestamps) * idx) // 4]
        high = timestamps[(len(timestamps) * (idx + 1)) // 4] if idx < 3 else math.inf
        bucket_depth = [e for e in current_depth if low <= e.timestamp_ns <= high]
        bucket_trades = [e for e in current_trades if low <= e.timestamp_ns <= high]
        if bucket_depth:
            results.append(_run(config, current_snapshot, bucket_depth, bucket_trades))
            book = OrderBook.from_snapshot(current_snapshot)
            for e in bucket_depth:
                book.apply_update(e)
            current_snapshot = L2Snapshot(
                timestamp_ns=book.timestamp_ns,
                last_update_id=book.last_update_id,
                bids=book.get_depth("bid", levels=1000),
                asks=book.get_depth("ask", levels=1000),
            )
    return results


def summarize(result: EventBacktestResult) -> dict[str, Any]:
    return {
        "fills": result.fills,
        "filled_qty": result.filled_qty,
        "net_pnl_usd": result.net_pnl_usd,
        "avg_adverse_selection_bps": result.avg_adverse_selection_bps,
        "as_by_horizon_bps": result.as_by_horizon,
        "final_inventory": result.final_inventory,
        "replacements": result.replacements,
        "cancels": result.cancels,
        "toxicity_suppressed_quotes": result.toxicity_suppressed_quotes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-dir", type=Path, required=True)
    parser.add_argument("--baseline-config", type=Path, default=Path("app/mm/config.json"))
    parser.add_argument("--candidate-config", type=Path, default=Path("app/mm/config_backtest_toxicity_v1.json"))
    parser.add_argument("--maker-fee-bps", type=float, default=2.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads((args.capture_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("bootstrap", {}).get("status") != "BRIDGED":
        raise SystemExit("CERTIFICATION_BLOCKED: capture bootstrap is not BRIDGED")
    if str(manifest.get("symbol", "")).upper() != "BTCUSDT":
        raise SystemExit("CERTIFICATION_BLOCKED: symbol must be BTCUSDT")

    snapshot = load_snapshot(args.capture_dir)
    depth, trades, counts = load_events(args.capture_dir)
    train_snapshot, train_depth, train_trades, validation_snapshot, valid_depth, valid_trades = _split_events(snapshot, depth, trades)

    baseline = _load_config(args.baseline_config, args.maker_fee_bps)
    candidate_base = _load_config(args.candidate_config, args.maker_fee_bps)

    train_baseline = _run(baseline, train_snapshot, train_depth, train_trades)
    candidate_results: list[tuple[tuple[float, int], V20Config, EventBacktestResult]] = []
    for candidate in _candidate_grid(candidate_base):
        result = _run(candidate, train_snapshot, train_depth, train_trades)
        candidate_results.append((_score(result), candidate, result))
    candidate_results.sort(key=lambda x: x[0], reverse=True)
    _, selected, selected_train = candidate_results[0]

    valid_baseline = _run(baseline, validation_snapshot, valid_depth, valid_trades)
    valid_candidate = _run(selected, validation_snapshot, valid_depth, valid_trades)

    candidate_buckets = _bucket_results(validation_snapshot, valid_depth, valid_trades, selected)
    baseline_buckets = _bucket_results(validation_snapshot, valid_depth, valid_trades, baseline)
    bucket_delta = [c.net_pnl_usd - b.net_pnl_usd for c, b in zip(candidate_buckets, baseline_buckets)]

    improvement = valid_candidate.net_pnl_usd - valid_baseline.net_pnl_usd
    pnl_positive = valid_candidate.net_pnl_usd > 0
    improvement_positive = improvement > 0
    as_improved = valid_candidate.avg_adverse_selection_bps <= valid_baseline.avg_adverse_selection_bps
    sufficient_fills = valid_candidate.fills >= 100 and valid_baseline.fills >= 100
    robust_buckets = len(bucket_delta) >= 4 and sum(x > 0 for x in bucket_delta) >= 3

    certified = all([pnl_positive, improvement_positive, as_improved, sufficient_fills, robust_buckets])

    report = {
        "certification": {
            "status": "PERFORMANCE_CERTIFIED" if certified else "NOT_CERTIFIED",
            "maker_fee_bps": args.maker_fee_bps,
            "rules": {
                "validation_candidate_net_pnl_usd_gt_0": pnl_positive,
                "candidate_beats_baseline_net_pnl": improvement_positive,
                "candidate_adverse_selection_not_worse": as_improved,
                "minimum_validation_fills": sufficient_fills,
                "at_least_3_of_4_validation_buckets_improve": robust_buckets,
            },
        },
        "capture": {**counts, "session_id": manifest.get("session_id"), "start_ns": manifest.get("start_ns"), "end_ns": manifest.get("end_ns")},
        "selected_candidate": {
            "base_half_spread_bps": selected.base_half_spread_bps,
            "toxicity_imbalance_threshold": selected.toxicity_imbalance_threshold,
            "toxicity_flow_threshold": selected.toxicity_flow_threshold,
            "microprice_skew_bps": selected.microprice_skew_bps,
        },
        "train": {"baseline": summarize(train_baseline), "selected_candidate": summarize(selected_train)},
        "validation": {"baseline": summarize(valid_baseline), "selected_candidate": summarize(valid_candidate), "net_pnl_improvement_usd": improvement, "quartile_delta_usd": bucket_delta},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if certified else 2


if __name__ == "__main__":
    raise SystemExit(main())
