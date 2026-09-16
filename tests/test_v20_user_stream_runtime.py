from app.mm.live_pnl import Fill
from app.mm.live_risk import LiveRiskGate, RiskLimits
from app.mm.execution import OrderStateManager
from app.mm.execution_gateway import ExecutionGateway
from app.mm.live_runtime import V20LiveRuntime
from app.mm.user_stream import UserStreamGuard
from app.mm.binance_user_stream import BinanceUSDMUserStream


class Adapter:
    def submit(self, submission):
        from app.mm.execution import ExecutionResult
        return ExecutionResult("NEW", "EX-1", "accepted", submission.client_id)

    def cancel(self, order_id):
        from app.mm.execution import ExecutionResult
        return ExecutionResult("CANCELED", order_id, "cancelled")


class FakeWS:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_user_stream_trade_fields_are_parsed():
    guard = UserStreamGuard()
    events = guard.parse({
        "e": "ORDER_TRADE_UPDATE", "E": 1000,
        "o": {"s":"BTCUSDT","c":"v20-1","i":1,"S":"BUY","X":"PARTIALLY_FILLED",
               "x":"TRADE","q":"0.01","z":"0.004","ap":"100000","l":"0.004","L":"99990",
               "t":42,"n":"0.08","N":"USDT"}
    })
    event = events[0]
    assert event.trade_id == "42"
    assert event.last_fill_qty == 0.004
    assert event.last_fill_price == 99990.0
    assert event.commission == 0.08


def test_quiet_stream_stays_healthy_after_transport_heartbeat():
    guard = UserStreamGuard(max_age_ms=5000)
    guard.connected_event(1000)
    assert guard.health(5999)[0] is True
    guard.heartbeat(6000)
    healthy, age, reason = guard.health(9999)
    assert healthy is True
    assert age == 3999
    assert reason == "ok"
    stale, _, reason = guard.health(11001)
    assert stale is False
    assert reason == "stale"


def test_expired_stream_clears_key_and_closes_socket():
    ws = FakeWS()
    statuses = []
    stream = BinanceUSDMUserStream(api_key="test-key", status_cb=statuses.append)
    stream.listen_key = "expired-key"
    stream._on_message(ws, '{"e":"listenKeyExpired","E":1000}')
    assert stream.listen_key is None
    assert ws.closed is True
    assert stream.guard.connected is False
    assert statuses[-1]["status"] == "LISTEN_KEY_EXPIRED"


def test_runtime_user_failure_latches_risk():
    risk = LiveRiskGate(RiskLimits())
    gateway = ExecutionGateway(Adapter(), risk, OrderStateManager(), live_enabled=False)
    runtime = V20LiveRuntime(gateway, risk)
    runtime.handle_user_stream_failure("MARGIN_CALL")
    assert risk.state.emergency_latched
