from __future__ import annotations

import json
from pathlib import Path
import sys


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("cert_reports")
    reports = sorted(root.rglob("v20_performance_certification.json"))
    if len(reports) < 2:
        raise SystemExit(f"CERTIFICATION_BLOCKED: expected at least 2 independent reports, found {len(reports)}")

    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in reports]
    statuses = [p.get("certification", {}).get("status") for p in payloads]
    all_pass = all(status == "PERFORMANCE_CERTIFIED" for status in statuses)

    summary = {
        "status": "PERFORMANCE_CERTIFIED" if all_pass else "NOT_CERTIFIED",
        "sessions": len(payloads),
        "session_statuses": statuses,
        "reports": [str(p) for p in reports],
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
