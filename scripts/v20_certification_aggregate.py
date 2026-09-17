from __future__ import annotations

import json
from pathlib import Path
import sys

EXPECTED_SESSIONS = {"A", "B", "C", "D"}
EXPECTED_MAKER_FEE_BPS = 1.0


def _session_key(path: Path) -> str | None:
    for parent in path.parents:
        name = parent.name.upper()
        if name in EXPECTED_SESSIONS:
            return name
        prefix = "V20-PERFORMANCE-CERTIFICATION-"
        if name.startswith(prefix):
            suffix = name[len(prefix):]
            if suffix in EXPECTED_SESSIONS:
                return suffix
    return None


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("cert_reports")
    reports = sorted(root.rglob("v20_performance_certification.json"))
    session_map: dict[str, Path] = {}
    for report in reports:
        session = _session_key(report)
        if session is not None:
            if session in session_map:
                raise SystemExit(f"CERTIFICATION_BLOCKED: duplicate report for session {session}")
            session_map[session] = report

    missing = sorted(EXPECTED_SESSIONS - set(session_map))
    if missing:
        raise SystemExit(
            f"CERTIFICATION_BLOCKED: expected exactly four independent reports A/B/C/D; missing {missing}"
        )
    if len(reports) != 4:
        raise SystemExit(
            f"CERTIFICATION_BLOCKED: expected exactly 4 certification reports, found {len(reports)}"
        )

    ordered_sessions = sorted(session_map)
    payloads = [json.loads(session_map[s].read_text(encoding="utf-8")) for s in ordered_sessions]

    capture_session_ids: list[str] = []
    for session, payload in zip(ordered_sessions, payloads):
        capture = payload.get("capture", {})
        report_session = str(capture.get("session_id", "")).strip()
        if not report_session:
            raise SystemExit(f"CERTIFICATION_BLOCKED: session {session} has no capture session_id")
        capture_session_ids.append(report_session)
        if float(payload.get("certification", {}).get("maker_fee_bps", -1)) != EXPECTED_MAKER_FEE_BPS:
            raise SystemExit(
                f"CERTIFICATION_BLOCKED: session {session} does not use the required {EXPECTED_MAKER_FEE_BPS} bps maker fee"
            )
        if capture.get("symbol", "BTCUSDT").upper() != "BTCUSDT":
            raise SystemExit(f"CERTIFICATION_BLOCKED: session {session} is not BTCUSDT")
        if int(capture.get("depth_events", 0)) < 500 or int(capture.get("trade_events", 0)) < 500:
            raise SystemExit(f"CERTIFICATION_BLOCKED: session {session} lacks minimum depth/trade event counts")

    if len(set(capture_session_ids)) != len(capture_session_ids):
        raise SystemExit("CERTIFICATION_BLOCKED: capture session_ids are not unique across A/B/C/D")

    statuses = [p.get("certification", {}).get("status") for p in payloads]
    all_pass = all(status == "PERFORMANCE_CERTIFIED" for status in statuses)

    summary = {
        "status": "PERFORMANCE_CERTIFIED" if all_pass else "NOT_CERTIFIED",
        "sessions": len(payloads),
        "session_ids": ordered_sessions,
        "session_statuses": statuses,
        "maker_fee_bps": EXPECTED_MAKER_FEE_BPS,
        "reports": [str(session_map[s]) for s in ordered_sessions],
        "validation_net_pnl_usd": [
            p.get("validation", {}).get("selected_candidate", {}).get("net_pnl_usd")
            for p in payloads
        ],
        "validation_baseline_net_pnl_usd": [
            p.get("validation", {}).get("baseline", {}).get("net_pnl_usd")
            for p in payloads
        ],
        "net_pnl_improvement_usd": [
            p.get("validation", {}).get("net_pnl_improvement_usd")
            for p in payloads
        ],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if all_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
