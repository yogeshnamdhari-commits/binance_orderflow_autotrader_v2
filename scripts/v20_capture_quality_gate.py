from __future__ import annotations

import json
import sys
from pathlib import Path

MIN_CAPTURE_DURATION_NS = 3_300 * 1_000_000_000


def inspect_capture(capture_dir: str | Path) -> dict[str, object]:
    root = Path(capture_dir)
    manifest_path = root / "manifest.json"
    snapshot_path = root / "snapshot.json"
    events_path = root / "events.jsonl"
    missing = [str(p) for p in (manifest_path, snapshot_path, events_path) if not p.is_file()]
    if missing:
        raise RuntimeError("missing capture files: " + ", ".join(missing))

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    event_count = 0
    type_counts: dict[str, int] = {}
    parse_errors = 0
    first_event_ns = None
    last_event_ns = None

    with events_path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            event_count += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                parse_errors += 1
                continue
            event_type = str(row.get("event_type") or "UNKNOWN")
            type_counts[event_type] = type_counts.get(event_type, 0) + 1
            receive_ns = row.get("receive_ns")
            if isinstance(receive_ns, int):
                first_event_ns = receive_ns if first_event_ns is None else min(first_event_ns, receive_ns)
                last_event_ns = receive_ns if last_event_ns is None else max(last_event_ns, receive_ns)

    trade_events = type_counts.get("trade", 0) + type_counts.get("aggTrade", 0)
    depth_events = type_counts.get("depthUpdate", 0)
    if trade_events <= 0:
        raise RuntimeError(
            "CERTIFICATION_CAPTURE_INVALID: no trade/aggTrade events; "
            "execution replay would be unable to model aggressive fills"
        )
    if depth_events <= 0:
        raise RuntimeError("CERTIFICATION_CAPTURE_INVALID: no depthUpdate events")
    if parse_errors > 0:
        raise RuntimeError(
            f"CERTIFICATION_CAPTURE_INVALID: {parse_errors} malformed JSON event rows"
        )
    if manifest.get("symbol") != "BTCUSDT":
        raise RuntimeError(
            f"CERTIFICATION_CAPTURE_INVALID: expected BTCUSDT, got {manifest.get('symbol')!r}"
        )
    start_ns = manifest.get("start_ns")
    end_ns = manifest.get("end_ns")
    if not isinstance(start_ns, int) or not isinstance(end_ns, int) or end_ns <= start_ns:
        raise RuntimeError("CERTIFICATION_CAPTURE_INVALID: missing or invalid capture duration")
    if end_ns - start_ns < MIN_CAPTURE_DURATION_NS:
        raise RuntimeError("CERTIFICATION_CAPTURE_INVALID: capture duration below 55 minutes")

    bootstrap = manifest.get("bootstrap") or {}
    if bootstrap.get("status") != "BRIDGED":
        raise RuntimeError(
            f"CERTIFICATION_CAPTURE_INVALID: bootstrap status={bootstrap.get('status')!r}"
        )
    if bootstrap.get("snapshot_source") not in {"REST", "WS_API"}:
        raise RuntimeError(
            "CERTIFICATION_CAPTURE_INVALID: snapshot source is not an approved Binance USD-M snapshot API"
        )

    snapshot_id = bootstrap.get("snapshot_last_update_id")
    first_U = bootstrap.get("first_U")
    first_u = bootstrap.get("first_u")
    if not all(isinstance(x, int) for x in (snapshot_id, first_U, first_u)):
        raise RuntimeError("CERTIFICATION_CAPTURE_INVALID: incomplete bootstrap sequence metadata")

    expected = snapshot_id + 1
    if not (first_U <= expected <= first_u):
        raise RuntimeError(
            "CERTIFICATION_CAPTURE_INVALID: first depth event does not bracket "
            f"snapshot_last_update_id+1 ({expected}); got U={first_U}, u={first_u}"
        )

    return {
        "capture_dir": str(root),
        "symbol": manifest.get("symbol"),
        "event_count": event_count,
        "type_counts": type_counts,
        "trade_events": trade_events,
        "depth_events": depth_events,
        "parse_errors": parse_errors,
        "first_event_receive_ns": first_event_ns,
        "last_event_receive_ns": last_event_ns,
        "bootstrap_status": bootstrap.get("status"),
        "duration_seconds": (end_ns - start_ns) / 1_000_000_000,
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python scripts/v20_capture_quality_gate.py <capture_dir>", file=sys.stderr)
        return 2
    try:
        report = inspect_capture(sys.argv[1])
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
