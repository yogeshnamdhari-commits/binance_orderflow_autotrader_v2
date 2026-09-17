import json
import sys
from pathlib import Path

from scripts.v20_certification_aggregate import main


def _write_report(
    root: Path,
    session: str,
    *,
    start_ns: int | None = None,
    end_ns: int | None = None,
) -> None:
    report_dir = root / f"v20-performance-certification-{session}"
    report_dir.mkdir(parents=True)
    payload = {
        "certification": {
            "status": "NOT_CERTIFIED",
            "maker_fee_bps": 1.0,
        },
        "capture": {
            "session_id": f"uuid-{session.lower()}",
            "symbol": "BTCUSDT",
            "start_ns": start_ns if start_ns is not None else 1_000_000_000,
            "end_ns": end_ns if end_ns is not None else 1_000_001_000,
            "depth_events": 1000,
            "trade_events": 1000,
        },
    }
    (report_dir / "v20_performance_certification.json").write_text(json.dumps(payload), encoding="utf-8")


def test_aggregate_accepts_downloaded_artifact_directories(tmp_path, monkeypatch):
    starts = {"A": 1_000_000_000, "B": 1_000_002_000, "C": 1_000_004_000, "D": 1_000_006_000}
    for session in "ABCD":
        start = starts[session]
        _write_report(tmp_path, session, start_ns=start, end_ns=start + 1_000)
    monkeypatch.setattr(sys, "argv", ["aggregate", str(tmp_path)])
    assert main() == 2


def test_aggregate_rejects_overlapping_capture_windows(tmp_path, monkeypatch):
    _write_report(tmp_path, "A", start_ns=1_000_000_000, end_ns=1_000_010_000)
    _write_report(tmp_path, "B", start_ns=1_000_005_000, end_ns=1_000_015_000)
    _write_report(tmp_path, "C", start_ns=1_000_020_000, end_ns=1_000_030_000)
    _write_report(tmp_path, "D", start_ns=1_000_040_000, end_ns=1_000_050_000)
    monkeypatch.setattr(sys, "argv", ["aggregate", str(tmp_path)])
    try:
        main()
    except SystemExit as exc:
        assert "capture windows overlap" in str(exc)
    else:
        raise AssertionError("expected overlap to block certification")
