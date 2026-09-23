from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any


EXPECTED_SESSIONS = ("A", "B", "C", "D")
ARTIFACT_PREFIX = "v20-performance-certification-"
REPORT_FILENAME = "v20_performance_certification.json"


def _metric(payload: dict[str, Any], *keys: str) -> Any:
    value: Any = payload
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def aggregate(root: Path) -> dict[str, Any]:
    reports: dict[str, Path] = {}
    discovery_errors: list[dict[str, str]] = []

    if not root.is_dir():
        discovery_errors.append({"reason": "report_root_missing", "path": str(root)})
    else:
        for artifact_dir in sorted(path for path in root.iterdir() if path.is_dir()):
            if not artifact_dir.name.startswith(ARTIFACT_PREFIX):
                continue
            session = artifact_dir.name.removeprefix(ARTIFACT_PREFIX)
            if session not in EXPECTED_SESSIONS:
                discovery_errors.append(
                    {"reason": "unexpected_session", "session": session, "path": str(artifact_dir)}
                )
                continue
            report = artifact_dir / REPORT_FILENAME
            if not report.is_file():
                discovery_errors.append(
                    {"reason": "report_missing", "session": session, "path": str(artifact_dir)}
                )
                continue
            if session in reports:
                discovery_errors.append(
                    {"reason": "duplicate_session", "session": session, "path": str(artifact_dir)}
                )
                continue
            reports[session] = report

    missing = [session for session in EXPECTED_SESSIONS if session not in reports]
    payloads: dict[str, dict[str, Any]] = {}
    parse_errors: list[dict[str, str]] = []
    identity_errors: list[dict[str, Any]] = []

    for session in EXPECTED_SESSIONS:
        report = reports.get(session)
        if report is None:
            continue
        try:
            payload = json.loads(report.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            parse_errors.append({"session": session, "path": str(report), "error": str(exc)})
            continue
        if not isinstance(payload, dict):
            parse_errors.append({"session": session, "path": str(report), "error": "report is not a JSON object"})
            continue
        reported_session = payload.get("session")
        if reported_session != session:
            identity_errors.append(
                {
                    "session": session,
                    "reported_session": reported_session,
                    "path": str(report),
                }
            )
            continue
        payloads[session] = payload

    blocked = bool(missing or discovery_errors or parse_errors or identity_errors)
    statuses = {
        session: payloads.get(session, {}).get("certification", {}).get("status", "MISSING")
        for session in EXPECTED_SESSIONS
    }
    all_pass = not blocked and all(
        statuses[session] == "PERFORMANCE_CERTIFIED" for session in EXPECTED_SESSIONS
    )

    if blocked:
        status = "CERTIFICATION_BLOCKED"
    elif all_pass:
        status = "PERFORMANCE_CERTIFIED"
    else:
        status = "NOT_CERTIFIED"

    return {
        "status": status,
        "expected_sessions": list(EXPECTED_SESSIONS),
        "sessions": len(payloads),
        "missing_sessions": missing,
        "session_statuses": [statuses[session] for session in EXPECTED_SESSIONS],
        "session_status_by_session": statuses,
        "discovery_errors": discovery_errors,
        "parse_errors": parse_errors,
        "identity_errors": identity_errors,
        "reports": {session: str(reports[session]) for session in EXPECTED_SESSIONS if session in reports},
        "validation_net_pnl_usd": [
            _metric(payloads.get(session, {}), "validation", "selected_candidate", "net_pnl_usd")
            for session in EXPECTED_SESSIONS
        ],
        "validation_baseline_net_pnl_usd": [
            _metric(payloads.get(session, {}), "validation", "baseline", "net_pnl_usd")
            for session in EXPECTED_SESSIONS
        ],
        "net_pnl_improvement_usd": [
            _metric(payloads.get(session, {}), "validation", "net_pnl_improvement_usd")
            for session in EXPECTED_SESSIONS
        ],
    }


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("cert_reports")
    summary = aggregate(root)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "PERFORMANCE_CERTIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
