import json
from pathlib import Path

from app.v17.preflight import PAPER, STATUS, run_preflight


def test_preflight_is_fail_closed():
    result = run_preflight()
    assert result["live_order_submission"] is False
    assert result["production_authorized"] is False
    assert result["status"] in {"READY_LOCKED", "FAIL"}


def test_paper_evidence_is_complete_and_did_not_submit_live_orders():
    paper = json.loads(PAPER.read_text(encoding="utf-8"))
    assert paper["status"] == "COMPLETE"
    assert paper["paper_trading_passed"] is True
    assert paper["live_order_submitted"] is False
    assert paper["n_trades"] > 0


def test_status_keeps_live_safety_lock():
    status = json.loads(STATUS.read_text(encoding="utf-8"))
    assert status["production_authorized"] is False
    assert status["live_order_submission"] is False
