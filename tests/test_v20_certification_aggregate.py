import json
import sys
from pathlib import Path

from scripts.v20_certification_aggregate import main


def _write_report(root: Path, session: str) -> None:
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
            "depth_events": 1000,
            "trade_events": 1000,
        },
    }
    (report_dir / "v20_performance_certification.json").write_text(json.dumps(payload), encoding="utf-8")


def test_aggregate_accepts_downloaded_artifact_directories(tmp_path, monkeypatch):
    for session in "ABCD":
        _write_report(tmp_path, session)
    monkeypatch.setattr(sys, "argv", ["aggregate", str(tmp_path)])
    assert main() == 2
