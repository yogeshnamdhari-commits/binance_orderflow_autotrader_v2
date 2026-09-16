from __future__ import annotations

import json
from pathlib import Path
import sys

EXPECTED_SESSIONS = {"A", "B", "C", "D"}


def _session_key(path: Path) -> str | None:
    for parent in path.parents:
        name = parent.name.upper()
        if name in EXPECTED_SESSIONS:
            return name
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
    statuses = [p.get("certification", {}).get("status") for p in payloads]
    all_pass = all(status == "PERFORMANCE_CERTIFIED" for status in statuses)

    summary = {
        "status": "PERFORMANCE_CERTIFIED" if all_pass else "NOT_CERTIFIED",
        "sessions": len(payloads),
        "session_ids": ordered_sessions,
        "session_statuses": statuses,
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
