"""Replay a local V20 raw Binance capture against two configs.

This research-only CLI requires an authentic local capture directory containing:
  - manifest.json
  - snapshot.json
  - events.jsonl

It never downloads synthetic market data and never places orders. The same
captured event stream is replayed independently for baseline and candidate so
that differences are attributable to configuration/logic changes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterator

from app.mm.book import L2Snapshot, L2Update
from app.mm.config import V20Config
from app.mm.event_backtest import EventBacktestResult, run_event_backtest
from app.mm.execution_replay import FundingRateEvent, MarkPriceEvent, Side, TradeEvent


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object in {path}")
    return payload


def load_snapshot(capture_dir: Path) -> L2Snapshot:
    payload = _load_json(capture_dir / "snapshot.json")
    try:
        return L2Snapshot(
            timestamp_ns=int(payload.get("T") or payload.get("E") or 0) * 1_000_000,
            last_update_id=int(payload["lastUpdateId"]),
            bids=[(float(price), float(qty)) for price, qty in payload["bids"]],
            asks=[(float(price), float(qty)) for price, qty in payload["asks"]],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid Binance depth snapshot: {capture_dir / 'snapshot.json'}") from exc


def _event_rows(capture_dir: Path) -> Iterator[dict[str, Any]]:
    path = capture_dir / "events.jsonl"
    if not path.is_file():
        raise FileNotFoundError(
            f"raw capture not found: {path}. Raw events are intentionally kept local."
        )
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at {path}:{line_no}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"non-object event row at {path}:{line_no}")
            yield row


def load_events(capture_dir: Path) -> tuple[list[L2Update], list[TradeEvent], dict[str, int]]:
    manifest = _load_json(capture_dir / "manifest.json")
    snapshot = load_snapshot(capture_dir)
    expected_count = int(manifest.get("event_count", 0))

    depth: list[L2Update] = []
    trades: list[TradeEvent] = []
    row_count = 0
    malformed = 0
    previous_depth_u = snapshot.last_update_id
    first_depth = True
    reconnects = 0
    gaps_detected = 0

    for row in _event_rows(capture_dir):
        row_count += 1
        raw = row.get("raw_json")
        event_type = row.get("event_type")
        if event_type == "reconnect":
            # Binance's new stream does not guarantee pu continuity across a
            # reconnect. Reset depth-sequence expectations at these exact
            # boundaries; the next depthUpdate becomes the new first event.
            reconnects += 1
            previous_depth_u = snapshot.last_update_id
            first_depth = True
            continue
        if not isinstance(raw, str):
            malformed += 1
            continue
        try:
            envelope = json.loads(raw)
            data = envelope.get("data", envelope)
            event_type = data.get("e")
            event_ms = int(data.get("E") or data.get("T") or 0)
            if event_type == "depthUpdate":
                U = int(data["U"])
                u = int(data["u"])
                pu = int(data.get("pu", previous_depth_u))
                if first_depth:
                    if not (U <= snapshot.last_update_id <= u):
                        raise ValueError(
                            "first depth event is not a valid snapshot bridge: "
                            f"snapshot={snapshot.last_update_id}, U={U}, u={u}"
                        )
                    first_depth = False
                    prev_id = snapshot.last_update_id
                else:
                    prev_id = pu
                    if prev_id != previous_depth_u:
                        gaps_detected += 1
                        raise ValueError(
                            "L2 sequence gap in capture: "
                            f"expected pu={previous_depth_u}, got pu={prev_id}, "
                            f"U={U}, u={u}"
                        )
                depth.append(
                    L2Update(
                        timestamp_ns=event_ms * 1_000_000,
                        first_update_id=U,
                        final_update_id=u,
                        prev_final_update_id=prev_id,
                        bids=[(float(p), float(q)) for p, q in data.get("b", [])],
                        asks=[(float(p), float(q)) for p, q in data.get("a", [])],
                    )
                )
                previous_depth_u = u
            elif event_type in {"trade", "aggTrade"}:
                trade_id = int(data.get("t", data.get("a", row_count)))
                maker_is_buyer = bool(data.get("m", False))
                aggressor = Side.SELL if maker_is_buyer else Side.BUY
                trades.append(
                    TradeEvent(
                        timestamp_ns=event_ms * 1_000_000,
                        price=float(data["p"]),
                        qty=float(data["q"]),
                        aggressor_side=aggressor,
                        event_seq=trade_id,
                    )
                )
        except ValueError:
            raise
        except (KeyError, TypeError, json.JSONDecodeError):
            malformed += 1

    if expected_count and row_count != expected_count:
        raise ValueError(
            f"capture event_count mismatch: manifest={expected_count}, rows={row_count}"
        )
    if malformed:
        raise ValueError(f"capture contains {malformed} malformed/unusable raw event rows")
    if not depth:
        raise ValueError("capture contains no depth events after the snapshot bridge")
    return depth, trades, {
        "raw_rows": row_count,
        "depth_events": len(depth),
        "trade_events": len(trades),
        "reconnect_markers": reconnects,
        "sequence_gaps_detected": gaps_detected,
    }


def load_perpetual_auxiliary_events(
    capture_dir: Path,
) -> tuple[list[MarkPriceEvent], list[FundingRateEvent]]:
    """Load mark-price/funding observations from an authentic USDⓈ-M capture."""
    marks: list[MarkPriceEvent] = []
    funding_by_time: dict[int, FundingRateEvent] = {}
    for row in _event_rows(capture_dir):
        if row.get("event_type") != "markPriceUpdate":
            continue
        envelope = json.loads(row["raw_json"])
        data = envelope.get("data", envelope)
        if data.get("e") != "markPriceUpdate":
            continue
        event_ms = int(data.get("E") or 0)
        mark = float(data["p"])
        next_funding_ms = int(data.get("T") or 0)
        rate = float(data["r"]) if data.get("r") not in (None, "") else None
        marks.append(
            MarkPriceEvent(
                timestamp_ns=event_ms * 1_000_000,
                mark_price=mark,
                next_funding_time_ns=next_funding_ms * 1_000_000,
                funding_rate=rate,
            )
        )
        if rate is not None and next_funding_ms > 0:
            funding_by_time[next_funding_ms * 1_000_000] = FundingRateEvent(
                timestamp_ns=next_funding_ms * 1_000_000,
                funding_rate=rate,
                mark_price=None,
            )
    return marks, sorted(funding_by_time.values(), key=lambda x: x.timestamp_ns)


def summarize(result: EventBacktestResult) -> dict[str, Any]:
    return {
        "fills": result.fills,
        "filled_qty": result.filled_qty,
        "fees_usd": result.fees_usd,
        "realized_pnl_usd": result.realized_pnl_usd,
        "inventory_mtm_usd": result.inventory_mtm_usd,
        "net_pnl_usd": result.net_pnl_usd,
        "avg_adverse_selection_bps": result.avg_adverse_selection_bps,
        "as_by_horizon_bps": result.as_by_horizon,
        "final_inventory": result.final_inventory,
        "replacements": result.replacements,
        "cancels": result.cancels,
        "toxicity_suppressed_quotes": result.toxicity_suppressed_quotes,
        "toxic_flow_imbalance_mean": result.toxic_flow_imbalance_mean,
        "gross_spread_capture_usd": result.gross_spread_capture_usd,
        "adverse_selection_usd": result.adverse_selection_usd,
        "execution_effects_usd": result.execution_effects_usd,
        "buy_fills": result.buy_fills,
        "sell_fills": result.sell_fills,
        "buy_filled_qty": result.buy_filled_qty,
        "sell_filled_qty": result.sell_filled_qty,
        "quote_crossings_detected": result.quote_crossings_detected,
        "quote_crossings_suppressed": result.quote_crossings_suppressed,
        "avg_fill_holding_time_ns": result.avg_fill_holding_time_ns,
        "funding_pnl_usd": result.funding_pnl_usd,
        "final_mark_price": result.final_mark_price,
    }


def _run(
    capture_dir: Path,
    config_path: Path,
    snapshot: L2Snapshot,
    depth: list[L2Update],
    trades: list[TradeEvent],
    marks: list[MarkPriceEvent] | None = None,
    funding: list[FundingRateEvent] | None = None,
) -> tuple[EventBacktestResult, str]:
    config, config_hash = V20Config.load_authoritative(str(config_path))
    if config.symbol.upper() != "BTCUSDT":
        raise ValueError(f"capture runner currently requires BTCUSDT, got {config.symbol}")
    result = run_event_backtest(
        snapshot, depth, trades, config,
        mark_price_events=marks or (),
        funding_events=funding or (),
    )
    return result, config_hash


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-dir", required=True, type=Path)
    parser.add_argument("--baseline-config", default="app/mm/config.json", type=Path)
    parser.add_argument("--candidate-config", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    capture_dir = args.capture_dir
    manifest = _load_json(capture_dir / "manifest.json")
    if manifest.get("bootstrap", {}).get("status") != "BRIDGED":
        raise SystemExit("capture bootstrap is not BRIDGED; refusing to backtest")
    if str(manifest.get("symbol", "")).upper() != "BTCUSDT":
        raise SystemExit("capture symbol must be BTCUSDT")

    snapshot = load_snapshot(capture_dir)
    depth, trades, counts = load_events(capture_dir)
    marks, funding = load_perpetual_auxiliary_events(capture_dir)
    if manifest.get("instrument") == "PERPETUAL" and (not marks or not funding):
        raise SystemExit("perpetual capture must contain markPriceUpdate/funding observations")
    baseline, baseline_hash = _run(
        capture_dir, args.baseline_config, snapshot, depth, trades, marks, funding
    )
    candidate, candidate_hash = _run(
        capture_dir, args.candidate_config, snapshot, depth, trades, marks, funding
    )

    report = {
        "capture": {
            "session_id": manifest.get("session_id"),
            "symbol": manifest.get("symbol"),
            "schema_version": manifest.get("schema_version"),
            "start_ns": manifest.get("start_ns"),
            "end_ns": manifest.get("end_ns"),
            **counts,
            "mark_price_events": len(marks),
            "funding_events": len(funding),
        },
        "baseline": {"config": str(args.baseline_config), "config_sha256": baseline_hash, **summarize(baseline)},
        "candidate": {"config": str(args.candidate_config), "config_sha256": candidate_hash, **summarize(candidate)},
        "delta_candidate_minus_baseline": {
            "net_pnl_usd": candidate.net_pnl_usd - baseline.net_pnl_usd,
            "avg_adverse_selection_bps": candidate.avg_adverse_selection_bps - baseline.avg_adverse_selection_bps,
            "fills": candidate.fills - baseline.fills,
            "filled_qty": candidate.filled_qty - baseline.filled_qty,
            "replacements": candidate.replacements - baseline.replacements,
            "cancels": candidate.cancels - baseline.cancels,
            "gross_spread_capture_usd": candidate.gross_spread_capture_usd - baseline.gross_spread_capture_usd,
            "fees_usd": candidate.fees_usd - baseline.fees_usd,
            "adverse_selection_usd": candidate.adverse_selection_usd - baseline.adverse_selection_usd,
            "buy_fills": candidate.buy_fills - baseline.buy_fills,
            "sell_fills": candidate.sell_fills - baseline.sell_fills,
            "quote_crossings_detected": candidate.quote_crossings_detected - baseline.quote_crossings_detected,
        },
    }

    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
