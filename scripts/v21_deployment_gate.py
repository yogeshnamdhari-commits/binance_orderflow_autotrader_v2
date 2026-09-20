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
    expected_git_commit: str | None = None,
    expected_research_run_id: str | None = None,
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

    provenance_reports = {
        "economic": econ,
        "paper": paper,
        "testnet": testnet,
        "tests": tests,
    }
    provenance_ok = True
    provenance_reasons: list[str] = []

    research_run_id = str(econ.get("certification_run_id", ""))
    if expected_research_run_id:
        if research_run_id != expected_research_run_id:
            provenance_ok = False
            provenance_reasons.append(
                f"research_run_id_mismatch:{research_run_id}!={expected_research_run_id}"
            )
    if expected_git_commit:
        for name, evidence in provenance_reports.items():
            evidence_sha = str(evidence.get("github_sha", ""))
            if evidence_sha != expected_git_commit:
                provenance_ok = False
                provenance_reasons.append(
                    f"{name}_git_commit_mismatch:{evidence_sha}!={expected_git_commit}"
                )
        bundle_sha = str(bundle.get("source_commit", ""))
        if bundle_sha != expected_git_commit:
            provenance_ok = False
            provenance_reasons.append(
                f"model_bundle_git_commit_mismatch:{bundle_sha}!={expected_git_commit}"
            )

    checks = {
        "economic_certified": econ.get("status") == "CERTIFIED",
        "economic_certification_scope_safe": (
            econ.get("execution_scope") == "RESEARCH_ONLY"
            and econ.get("live_order_submission") is False
        ),
        "research_run_provenance_valid": provenance_ok,
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
    header_material = {
        "schema_version": 1,
        "research_run_id": research_run_id,
        "github_sha": expected_git_commit or econ.get("github_sha", ""),
        "execution_scope": "NON_LIVE",
    }
    authorization_header = hashlib.sha256(
        json.dumps(header_material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "status": "DEPLOYMENT_CERTIFIED_NON_LIVE" if authorized else "LOCKED",
        "deployment_scope": "NON_LIVE",
        "live_order_submission": False,
        "execution_authorized": False,
        "checks": checks,
        "model_bundle_sha256": expected,
        "expected_git_commit": expected_git_commit or "",
        "expected_research_run_id": expected_research_run_id or "",
        "certification_run_id": research_run_id,
        "authorization_header": "App-Public-Action-Certification-V21: orderflow:" + authorization_header,
        "authorization_header_sha256": authorization_header,
        "provenance_reasons": provenance_reasons,
        "reason": (
            "Certification gates passed for a non-live deployment scope; live execution still requires a separate production authorization path."
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
    parser.add_argument("--expected-git-commit", default="")
    parser.add_argument("--expected-research-run-id", default="")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = evaluate(
        economic_certification=args.economic_certification,
        model_bundle=args.model_bundle,
        paper_evidence=args.paper_evidence,
        testnet_evidence=args.testnet_evidence,
        tests_evidence=args.tests_evidence,
        explicit_authorization=args.explicit_authorization,
        expected_git_commit=args.expected_git_commit or None,
        expected_research_run_id=args.expected_research_run_id or None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "DEPLOYMENT_CERTIFIED_NON_LIVE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
