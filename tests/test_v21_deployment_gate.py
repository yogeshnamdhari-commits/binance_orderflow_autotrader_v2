import hashlib
import json
from pathlib import Path

from scripts.v21_deployment_gate import evaluate


def _bundle(tmp_path: Path) -> Path:
    payload = {
        "schema_version": 1,
        "features": [],
        "production_inference": {"training_in_live_process": False},
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["bundle_sha256"] = hashlib.sha256(raw).hexdigest()
    p = tmp_path / "bundle.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _write(tmp_path: Path, name: str, payload: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _common(tmp_path: Path):
    commit = "abc123"
    return {
        "economic_certification": _write(tmp_path, "econ.json", {"status": "CERTIFIED", "github_sha": commit, "certification_run_id": "research-123", "execution_scope": "RESEARCH_ONLY", "live_order_submission": False}),
        "model_bundle": _bundle(tmp_path),
        "paper_evidence": _write(tmp_path, "paper.json", {"status": "PASS", "github_sha": commit}),
        "testnet_evidence": _write(
            tmp_path,
            "testnet.json",
            {
                "private_stream_connected": True,
                "reconciled_open_orders": True,
                "reconciled_position_snapshot": True,
                "rest_order_lifecycle": "PASS",
                "github_sha": commit,
            },
        ),
        "tests_evidence": _write(
            tmp_path,
            "tests.json",
            {"status": "PASS", "risk_controls_passed": True, "github_sha": commit},
        ),
    }


def test_deployment_gate_requires_explicit_authorization(tmp_path):
    args = _common(tmp_path)
    bundle = json.loads(args["model_bundle"].read_text())
    bundle["source_commit"] = "abc123"
    canonical = dict(bundle)
    canonical.pop("bundle_sha256", None)
    bundle["bundle_sha256"] = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    args["model_bundle"].write_text(json.dumps(bundle), encoding="utf-8")
    report = evaluate(**args, explicit_authorization=False, expected_git_commit="abc123")
    assert report["status"] == "LOCKED"
    assert report["checks"]["explicit_authorization"] is False
    assert report["live_order_submission"] is False


def test_deployment_gate_requires_authenticated_demo_lifecycle(tmp_path):
    args = _common(tmp_path)
    bad = json.loads(args["testnet_evidence"].read_text())
    bad["rest_order_lifecycle"] = "NOT_RUN"
    args["testnet_evidence"].write_text(json.dumps(bad), encoding="utf-8")
    report = evaluate(**args, explicit_authorization=True)
    assert report["status"] == "LOCKED"
    assert report["checks"]["authenticated_testnet_passed"] is False


def test_deployment_gate_authorizes_only_when_all_checks_pass(tmp_path):
    args = _common(tmp_path)
    report = evaluate(**args, explicit_authorization=True)
    assert report["status"] == "DEPLOYMENT_CERTIFIED_NON_LIVE"
    assert report["checks"]["economic_certified"] is True
    assert report["checks"]["model_bundle_hash_valid"] is True
    assert report["checks"]["authenticated_testnet_passed"] is True
    assert report["checks"]["tests_passed"] is True
    assert report["checks"]["risk_controls_passed"] is True
    assert report["live_order_submission"] is False


def test_deployment_gate_rejects_mixed_commit_evidence(tmp_path):
    args = _common(tmp_path)
    bad = json.loads(args["paper_evidence"].read_text())
    bad["github_sha"] = "different"
    args["paper_evidence"].write_text(json.dumps(bad), encoding="utf-8")
    bundle = json.loads(args["model_bundle"].read_text())
    bundle["source_commit"] = "abc123"
    canonical = dict(bundle)
    canonical.pop("bundle_sha256", None)
    bundle["bundle_sha256"] = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    args["model_bundle"].write_text(json.dumps(bundle), encoding="utf-8")
    report = evaluate(**args, explicit_authorization=True, expected_git_commit="abc123")
    assert report["status"] == "LOCKED"
    assert report["checks"]["evidence_commit_provenance_valid"] is False


def test_deployment_gate_rejects_mismatched_research_run(tmp_path):
    args = _common(tmp_path)
    report = evaluate(
        **args,
        explicit_authorization=True,
        expected_git_commit="abc123",
        expected_research_run_id="research-999",
    )
    assert report["status"] == "LOCKED"
    assert report["checks"]["research_run_provenance_valid"] is False
    assert any("research_run_id_mismatch" in r for r in report["provenance_reasons"])


def test_deployment_gate_emits_non_live_authorization_header(tmp_path):
    args = _common(tmp_path)
    report = evaluate(
        **args,
        explicit_authorization=True,
        expected_git_commit="abc123",
        expected_research_run_id="research-123",
    )
    assert report["status"] == "DEPLOYMENT_CERTIFIED_NON_LIVE"
    assert report["deployment_scope"] == "NON_LIVE"
    assert report["execution_authorized"] is False
    assert report["live_order_submission"] is False
    assert report["authorization_header"].startswith("App-Public-Action-Certification-V21: orderflow:")
