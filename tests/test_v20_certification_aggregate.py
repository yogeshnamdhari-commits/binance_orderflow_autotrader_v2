import json
from pathlib import Path

from scripts.v20_certification_aggregate import aggregate


def _report(session: str, status: str = "PERFORMANCE_CERTIFIED") -> dict:
    return {
        "session": session,
        "certification": {"status": status},
        "validation": {
            "baseline": {"net_pnl_usd": -1.0},
            "selected_candidate": {"net_pnl_usd": 1.0},
            "net_pnl_improvement_usd": 2.0,
        },
    }


def _write_report(root: Path, session: str, payload: dict | None = None) -> Path:
    artifact_dir = root / f"v20-performance-certification-{session}"
    artifact_dir.mkdir(parents=True)
    report = artifact_dir / "v20_performance_certification.json"
    report.write_text(json.dumps(payload if payload is not None else _report(session)), encoding="utf-8")
    return report


def test_aggregate_requires_all_four_session_artifacts(tmp_path):
    for session in ("A", "B", "C", "D"):
        _write_report(tmp_path, session)

    result = aggregate(tmp_path)

    assert result["status"] == "PERFORMANCE_CERTIFIED"
    assert result["missing_sessions"] == []
    assert result["session_statuses"] == ["PERFORMANCE_CERTIFIED"] * 4
    assert result["validation_net_pnl_usd"] == [1.0] * 4


def test_aggregate_blocks_missing_sessions(tmp_path):
    _write_report(tmp_path, "A")

    result = aggregate(tmp_path)

    assert result["status"] == "CERTIFICATION_BLOCKED"
    assert result["missing_sessions"] == ["B", "C", "D"]
    assert result["session_status_by_session"]["A"] == "PERFORMANCE_CERTIFIED"
    assert result["session_status_by_session"]["B"] == "MISSING"


def test_aggregate_rejects_flat_merged_reports(tmp_path):
    (tmp_path / "v20_performance_certification.json").write_text(
        json.dumps(_report("A")), encoding="utf-8"
    )

    result = aggregate(tmp_path)

    assert result["status"] == "CERTIFICATION_BLOCKED"
    assert result["missing_sessions"] == ["A", "B", "C", "D"]


def test_aggregate_rejects_report_session_identity_mismatch(tmp_path):
    _write_report(tmp_path, "A", _report("B"))
    for session in ("B", "C", "D"):
        _write_report(tmp_path, session)

    result = aggregate(tmp_path)

    assert result["status"] == "CERTIFICATION_BLOCKED"
    assert result["identity_errors"][0]["session"] == "A"
    assert result["identity_errors"][0]["reported_session"] == "B"


def test_aggregate_rejects_malformed_report(tmp_path):
    artifact_dir = tmp_path / "v20-performance-certification-A"
    artifact_dir.mkdir()
    (artifact_dir / "v20_performance_certification.json").write_text("{", encoding="utf-8")
    for session in ("B", "C", "D"):
        _write_report(tmp_path, session)

    result = aggregate(tmp_path)

    assert result["status"] == "CERTIFICATION_BLOCKED"
    assert result["parse_errors"][0]["session"] == "A"
