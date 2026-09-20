import hashlib
import json
import pathlib

from app.mm.execution import ExecutionResult, OrderStateManager
from app.mm.execution_gateway import ExecutionGateway
from app.mm.live_risk import LiveRiskGate, RiskLimits
from app.mm.v21_live_controller import V21LiveController
from app.models import BookState, DepthEvent
from app.research.v21_production_model import V21ModelBundle
from scripts.v21_orderflow_dataset import FEATURES


class Adapter:
    def submit(self, submission):
        return ExecutionResult("NEW", "EX-1", "accepted", submission.client_id)

    def cancel(self, order_id, symbol=None):
        return ExecutionResult("CANCELLED", order_id, "cancelled")

    def cancel_all(self, symbol):
        return ExecutionResult("CANCELLED_ALL", None, f"cancelled all {symbol}")


def bundle():
    n = len(FEATURES)
    payload = {
        "schema_version": 2,
        "model_family": "v21_two_stage_orderflow_conditional_markout_mm",
        "horizon_ms": 250,
        "features": list(FEATURES),
        "training_sessions": ["A"],
        "training_sizes": {"rows": 1000},
        "dataset_sha256": "0" * 64,
        "toxicity_dataset_sha256": "1" * 64,
        "move": {"mean": [0.0] * n, "scale": [1.0] * n, "coef": [0.0] * n, "intercept": 0.0},
        "direction": {"mean": [0.0] * n, "scale": [1.0] * n, "coef": [0.0] * n, "intercept": 0.0},
        "magnitude": {"coef": [0.0] * n, "intercept": 1.5},
        "markout_buy": {"coef": [0.0] * n, "intercept": 3.50},
        "markout_sell": {"coef": [0.0] * n, "intercept": 3.50},
        "production_inference": {"training_in_live_process": False, "feature_order_locked": True, "economic_signal_horizon_ms": 250},
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["bundle_sha256"] = hashlib.sha256(raw).hexdigest()
    path = pathlib.Path("/tmp/v21-controller-bundle.json")
    path.write_text(json.dumps(payload), encoding="utf-8")
    return V21ModelBundle.from_file(path)


def healthy_risk():
    risk = LiveRiskGate(RiskLimits(max_order_qty=0.01))
    risk.update_market_health(10, True)
    risk.update_user_stream_health(10, True)
    risk.update_reconciliation(True)
    risk.update_quote_age(10)
    risk.update_position(0.0, 100000.0)
    risk.update_orders(0)
    risk.update_pnl(0.0)
    risk.update_api_errors(0)
    return risk


def book():
    return BookState(
        last_update_id=10,
        bids={99990.0: 1.0, 99980.0: 1.0, 99970.0: 1.0, 99960.0: 1.0, 99950.0: 1.0},
        asks={100010.0: 1.0, 100020.0: 1.0, 100030.0: 1.0, 100040.0: 1.0, 100050.0: 1.0},
        synchronized=True,
        last_event_ms=1000,
    )


def test_controller_is_dry_run_by_default():
    risk = healthy_risk()
    gateway = ExecutionGateway(Adapter(), risk, OrderStateManager(), live_enabled=False)
    controller = V21LiveController(
        gateway=gateway, risk=risk, model=bundle(), symbol="BTCUSDT",
        tick_size=0.1, maker_fee_bps=1.0, live_authorized=False
    )
    plan = controller.on_depth(DepthEvent(1000, 11, 11, [], []), book(), 0.0)
    result = controller.apply_plan(plan)
    assert result["status"] == "DRY_RUN_BLOCKED"
    assert gateway.manager.open_orders == []


def test_controller_rejects_unsynchronized_book():
    risk = healthy_risk()
    gateway = ExecutionGateway(Adapter(), risk, OrderStateManager(), live_enabled=False)
    controller = V21LiveController(
        gateway=gateway, risk=risk, model=bundle(), symbol="BTCUSDT",
        tick_size=0.1, maker_fee_bps=1.0
    )
    bad = book()
    bad.synchronized = False
    try:
        controller.on_depth(DepthEvent(1000, 11, 11, [], []), bad, 0.0)
    except RuntimeError as exc:
        assert str(exc) == "book_not_synchronized"
    else:
        raise AssertionError("unsynchronized book was accepted")

def test_controller_kill_switch_cancels_exchange_symbol_orders():
    risk = healthy_risk()
    gateway = ExecutionGateway(Adapter(), risk, OrderStateManager(), live_enabled=True)
    controller = V21LiveController(
        gateway=gateway, risk=risk, model=bundle(), symbol="BTCUSDT",
        tick_size=0.1, maker_fee_bps=1.0, live_authorized=False
    )
    result = controller.cancel_all()
    assert result["status"] == "CANCELLED_ALL"
    assert result["actions"][0]["action"] == "cancel_all_exchange"
    assert result["actions"][0]["result"] == "CANCELLED_ALL"


def test_controller_requires_both_live_authorization_gates():
    for gateway_live, controller_authorized in ((True, False), (False, True)):
        risk = healthy_risk()
        gateway = ExecutionGateway(Adapter(), risk, OrderStateManager(), live_enabled=gateway_live)
        controller = V21LiveController(
            gateway=gateway,
            risk=risk,
            model=bundle(),
            symbol="BTCUSDT",
            tick_size=0.1,
            maker_fee_bps=1.0,
            live_authorized=controller_authorized,
        )
        plan = controller.on_depth(DepthEvent(1000, 11, 11, [], []), book(), 0.0)
        result = controller.apply_plan(plan)
        assert result["status"] == "DRY_RUN_BLOCKED"
        assert gateway.manager.open_orders == []


def test_controller_can_submit_only_when_both_gates_and_risk_are_healthy():
    risk = healthy_risk()
    gateway = ExecutionGateway(Adapter(), risk, OrderStateManager(), live_enabled=True)
    controller = V21LiveController(
        gateway=gateway,
        risk=risk,
        model=bundle(),
        symbol="BTCUSDT",
        tick_size=0.1,
        maker_fee_bps=1.0,
        live_authorized=True,
    )
    plan = controller.on_depth(DepthEvent(1000, 11, 11, [], []), book(), 0.0)
    result = controller.apply_plan(plan)
    assert result["status"] == "LIVE_APPLIED"
    assert any(action["action"] == "submit" for action in result["actions"])
