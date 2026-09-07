"""Tests for V13 production gate and temporal separation."""
import json
from pathlib import Path

import pytest

from app.v13.production import V13ProductionGate, LIVE_ORDER_SUBMISSION
from app.v13.config import V13Config


def test_v13_live_order_submission_hard_false():
    assert LIVE_ORDER_SUBMISSION is False


def test_v13_gate_locked_without_artifacts(tmp_path):
    gate = V13ProductionGate(tmp_path)
    gates = gate.evaluate()
    assert gates["data_integrity"] == "NOT_STARTED"
    ready, _ = gate.is_production_ready()
    assert ready is False


def test_v13_gate_reports_fail_on_forward_fail(tmp_path):
    (tmp_path / "v13_forward_result.json").write_text(json.dumps({
        "status": "FAIL",
        "gate_conditions": {"sufficient_observations": True, "net_ev_positive": False,
                            "statistically_significant": False},
        "regimes": {},
    }), encoding="utf-8")
    gate = V13ProductionGate(tmp_path)
    gates = gate.evaluate()
    assert gates["independent_forward_test"] == "FAIL"
    assert gates["positive_net_ev"] == "FAIL"
    ready, reason = gate.is_production_ready()
    assert ready is False


def test_v13_config_horizon_not_500ms():
    """V13 must NOT use the V12 500ms horizon."""
    assert V13Config.prediction_horizon_ms != 500
    assert V13Config.prediction_horizon_ms == 2000
