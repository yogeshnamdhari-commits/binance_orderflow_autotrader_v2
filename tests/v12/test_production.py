"""Tests for V12 production gate — must be HARD-LOCKED (Rule 28)."""
import json
from pathlib import Path

import pytest

from app.v12.production import (
    ProductionGate,
    V12ProductionExecutor,
    LIVE_ORDER_SUBMISSION,
    ProductionCredentials,
)


def test_live_order_submission_is_hard_false():
    assert LIVE_ORDER_SUBMISSION is False


def test_production_gate_evaluates_when_forward_result_missing(tmp_path):
    gate = ProductionGate(tmp_path)
    gates = gate.evaluate()
    # No evidence at all -> every required gate NOT_STARTED
    assert gates["data_integrity"] == "NOT_STARTED"
    assert gates["independent_forward_test"] == "NOT_STARTED"
    ready, reason = gate.is_production_ready()
    assert ready is False
    assert LIVE_ORDER_SUBMISSION is False


def test_production_gate_reports_fail_when_forward_fails(tmp_path):
    (tmp_path / "v12_forward_result.json").write_text(json.dumps({
        "status": "FAIL",
        "gate_conditions": {"sufficient_observations": True, "net_ev_positive": False,
                            "statistically_significant": False},
        "regimes": [],
    }), encoding="utf-8")
    gate = ProductionGate(tmp_path)
    gates = gate.evaluate()
    assert gates["independent_forward_test"] == "FAIL"
    assert gates["positive_net_ev"] == "FAIL"
    assert gates["statistical_robustness"] == "FAIL"
    ready, reason = gate.is_production_ready()
    assert ready is False


def test_production_executor_blocks_live_orders(tmp_path):
    creds = ProductionCredentials(api_key="k", api_secret="s")
    exec_obj = V12ProductionExecutor(creds=creds, evidence_dir=tmp_path)
    assert exec_obj.is_live_enabled() is False
    with pytest.raises(RuntimeError):
        exec_obj.submit_live_order(side="BUY", qty_btc=0.01, price=50000)
