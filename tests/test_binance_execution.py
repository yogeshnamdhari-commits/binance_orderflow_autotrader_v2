from app.mm.binance_execution import BinanceExecutionConfig, BinanceUSDMExecutionAdapter
from app.mm.execution_gateway import Submission


class Response:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None


def test_binance_adapter_uses_post_only_gtx():
    adapter = BinanceUSDMExecutionAdapter(
        BinanceExecutionConfig("https://testnet.binancefuture.com", "key", "secret")
    )
    captured = {}

    def signed(method, path, params):
        captured.update(method=method, path=path, params=params)
        return Response({"orderId": 123, "clientOrderId": "V21-1", "status": "NEW"})

    adapter._signed_request = signed
    adapter._constraints = {}
    adapter._exchange_info_loaded = True
    adapter._constraints_for = lambda symbol: type(
        "C",
        (),
        {"validate": lambda self, price, qty: (True, ())},
    )()

    result = adapter.submit(Submission("btcusdt", "buy", 0.001, 90000.0, "V21-1"))

    assert result.status == "NEW"
    assert captured["path"] == "/fapi/v1/order"
    assert captured["params"]["symbol"] == "BTCUSDT"
    assert captured["params"]["side"] == "BUY"
    assert captured["params"]["timeInForce"] == "GTX"


def test_binance_adapter_cancel_all_symbol_scope():
    adapter = BinanceUSDMExecutionAdapter(
        BinanceExecutionConfig("https://testnet.binancefuture.com", "key", "secret")
    )
    captured = {}

    def signed(method, path, params):
        captured.update(method=method, path=path, params=params)
        return Response({"code": 200, "msg": "The operation of cancel all open orders is done."})

    adapter._signed_request = signed

    result = adapter.cancel_all("btcusdt")

    assert result.status == "CANCELLED_ALL"
    assert captured == {
        "method": "DELETE",
        "path": "/fapi/v1/allOpenOrders",
        "params": {"symbol": "BTCUSDT"},
    }
