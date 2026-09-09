import pytest

from app.binance_execution import BinanceExecutionError, BinanceFuturesExecution


def test_live_execution_is_locked_by_default():
    ex = BinanceFuturesExecution(api_key="k", api_secret="s")
    assert ex.can_submit_live is False
    with pytest.raises(BinanceExecutionError):
        ex.submit_market("BTCUSDT", "BUY", "0.001")


def test_governance_lock_overrides_runtime_enable():
    ex = BinanceFuturesExecution(
        api_key="k", api_secret="s", live_enabled=True, governance_locked=True
    )
    assert ex.can_submit_live is False
    with pytest.raises(BinanceExecutionError):
        ex.submit_market("BTCUSDT", "BUY", "0.001")


def test_explicit_enable_requires_credentials():
    ex = BinanceFuturesExecution(live_enabled=True, governance_locked=False)
    assert ex.can_submit_live is False
    with pytest.raises(BinanceExecutionError):
        ex.submit_market("BTCUSDT", "BUY", "0.001")


def test_parse_order_is_deterministic():
    data = {
        "orderId": 123,
        "clientOrderId": "of-123",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "status": "FILLED",
        "origQty": "0.001",
        "executedQty": "0.001",
        "avgPrice": "100000.0",
    }
    order = BinanceFuturesExecution._parse_order(data)
    assert order.order_id == 123
    assert order.client_order_id == "of-123"
    assert order.status == "FILLED"
    assert order.executed_qty == "0.001"
