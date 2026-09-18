import pytest

from app.mm.execution import ExecutionResult, OrderStateManager
from app.mm.execution_gateway import ExecutionGateway, Submission
from app.mm.live_market_data import MarketDataGuard
from app.mm.live_risk import LiveRiskGate, RiskLimits
from app.mm.production_gate import evaluate_readiness
from app.mm.reconciliation import (
    ExchangeOrder,
    LocalOrder,
    PositionState,
    reconcile,
)
from app.mm.user_stream import UserStreamGuard


class RejectingAdapter:
    def submit(self, submission):
        return ExecutionResult("SUBMITTED", "EX-1", "submitted", submission.client_id)

    def cancel(self, order_id):
        return ExecutionResult("CANCELLED", order_id, "cancelled")


def healthy_gate():
    gate = LiveRiskGate(RiskLimits(max_order_qty=0.01))
    gate.update_market_health(10, True)
    gate.update_user_stream_health(10, True)
    gate.update_reconciliation(True)
    gate.update_quote_age(10)
    gate.update_position(0.0, 100000.0)
    gate.update_orders(0)
    gate.update_pnl(0.0)
    gate.update_api_errors(0)
    return gate


def test_execution_gateway_is_fail_closed_by_default():
    manager = OrderStateManager()
    gate = healthy_gate()
    gateway = ExecutionGateway(RejectingAdapter(), gate, manager, live_enabled=False)
    result = gateway.submit(Submission("BTCUSDT", "BUY", 0.001, 100000.0, "V20-1"))
    assert result.status == "BLOCKED_LIVE_DISABLED"


def test_risk_gate_blocks_stale_market_data_and_large_orders():
    gate = healthy_gate()
    gate.update_market_health(2000, True)
    allowed, reasons = gate.can_submit(0.02)
    assert not allowed
    assert "market_data_unhealthy" in reasons
    assert "order_size_limit" in reasons


def test_reconciliation_detects_position_and_order_mismatch():
    local = {"cid": LocalOrder("cid", "1", "BTCUSDT", "BUY", 1.0, 0.5, "PARTIAL")}
    exchange = {"cid": ExchangeOrder("cid", "1", "BTCUSDT", "BUY", 1.0, 0.0, "NEW")}
    result = reconcile(local, exchange, PositionState("BTCUSDT", 0.5), PositionState("BTCUSDT", 0.0))
    assert not result.ok
    assert "order_fill_mismatch:cid" in result.reasons
    assert "position_quantity_mismatch" in result.reasons


def test_market_data_guard_detects_gap():
    guard = MarketDataGuard(max_age_ms=1000)
    assert guard.accept_depth(1, 1, 1000, 1000).ready
    result = guard.accept_depth(3, 3, 1100, 1100)
    assert not result.ready
    assert result.reason == "sequence_gap"


def test_user_stream_guard_rejects_stale_connection():
    guard = UserStreamGuard(max_age_ms=100)
    guard.connected_event(1000)
    ok, age, reason = guard.health(1201)
    assert not ok
    assert age == 201
    assert reason == "stale"


def test_production_gate_is_not_ready_when_live_submission_enabled():
    result = evaluate_readiness(
        git_commit="abc123",
        config_path="app/mm/config.json",
        expected_config_sha256=None,
        live_order_submission=True,
        market_ready=True,
        user_stream_ready=True,
        reconciled=True,
        risk_ready=True,
        tests_passed=True,
    )
    assert not result.ready
    assert "live_submission_requires_explicit_deployment_gate" in result.reasons
