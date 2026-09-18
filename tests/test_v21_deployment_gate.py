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
    return {
        "economic_certification": _write(tmp_path, "econ.json", {"status": "CERTIFIED"}),
        "model_bundle": _bundle(tmp_path),
        "paper_evidence": _write(tmp_path, "paper.json", {"status": "PASS"}),
        "testnet_evidence": _write(
            tmp_path,
            "testnet.json",
            {
                "private_stream_connected": True,
                "reconciled_open_orders": True,
                "reconciled_position_snapshot": True,
                "rest_order_lifecycle": "PASS",
            },
        ),
        "tests_evidence": _write(
            tmp_path,
            "tests.json",
            {"status": "PASS", "risk_controls_passed": True},
        ),
    }


def test_deployment_gate_requires_explicit_authorization(tmp_path):
    args = _common(tmp_path)
    report = evaluate(**args, explicit_authorization=False)
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
    assert report["status"] == "DEPLOYMENT_AUTHORIZED"
    assert report["checks"]["economic_certified"] is True
    assert report["checks"]["model_bundle_hash_valid"] is True
    assert report["checks"]["authenticated_testnet_passed"] is True
    assert report["checks"]["tests_passed"] is True
    assert report["checks"]["risk_controls_passed"] is True
    assert report["live_order_submission"] is False
