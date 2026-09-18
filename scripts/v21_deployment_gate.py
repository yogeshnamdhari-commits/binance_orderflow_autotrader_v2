"""Final V21 deployment gate.

Economic research certification is necessary but not sufficient for real-money
deployment. This gate also requires a hash-verified frozen model, independent
paper validation, authenticated demo/testnet lifecycle evidence, production
risk controls, passing tests, and explicit operator authorization.

It never turns live submission on.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate(
    *,
    economic_certification: Path,
    model_bundle: Path,
    paper_evidence: Path,
    testnet_evidence: Path,
    tests_evidence: Path,
    explicit_authorization: bool,
) -> dict[str, Any]:
    econ = _read(economic_certification)
    paper = _read(paper_evidence)
    testnet = _read(testnet_evidence)
    tests = _read(tests_evidence)

    bundle = _read(model_bundle)
    expected = str(bundle.get("bundle_sha256", ""))
    canonical = dict(bundle)
    canonical.pop("bundle_sha256", None)
    actual = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    checks = {
        "economic_certified": econ.get("status") == "CERTIFIED",
        "model_bundle_present": model_bundle.is_file(),
        "model_bundle_hash_valid": bool(expected) and expected == actual,
        "model_training_disabled_in_live": (
            bundle.get("production_inference", {}).get("training_in_live_process") is False
        ),
        "paper_validation_passed": paper.get("status") == "PASS",
        "authenticated_testnet_passed": (
            testnet.get("private_stream_connected") is True
            and testnet.get("reconciled_open_orders") is True
            and testnet.get("reconciled_position_snapshot") is True
            and testnet.get("rest_order_lifecycle") == "PASS"
        ),
        "tests_passed": tests.get("status") == "PASS",
        "risk_controls_passed": bool(tests.get("risk_controls_passed", False)),
        "explicit_authorization": bool(explicit_authorization),
    }

    authorized = all(checks.values())
    return {
        "status": "DEPLOYMENT_AUTHORIZED" if authorized else "LOCKED",
        "live_order_submission": False,
        "checks": checks,
        "model_bundle_sha256": expected,
        "reason": (
            "All deployment gates passed; operator authorization is present."
            if authorized
            else "One or more deployment gates are missing; live submission remains disabled."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--economic-certification", type=Path, required=True)
    parser.add_argument("--model-bundle", type=Path, required=True)
    parser.add_argument("--paper-evidence", type=Path, required=True)
    parser.add_argument("--testnet-evidence", type=Path, required=True)
    parser.add_argument("--tests-evidence", type=Path, required=True)
    parser.add_argument("--explicit-authorization", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = evaluate(
        economic_certification=args.economic_certification,
        model_bundle=args.model_bundle,
        paper_evidence=args.paper_evidence,
        testnet_evidence=args.testnet_evidence,
        tests_evidence=args.tests_evidence,
        explicit_authorization=args.explicit_authorization,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "DEPLOYMENT_AUTHORIZED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
