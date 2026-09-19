from app.mm.binance_execution import BinanceExecutionConfig, BinanceUSDMExecutionAdapter


class Response:
    def __init__(self, payload):
        self.payload = payload
    def json(self):
        return self.payload
    def raise_for_status(self):
        return None


def test_server_time_calibration_offsets_signed_timestamp(monkeypatch):
    adapter = BinanceUSDMExecutionAdapter(
        BinanceExecutionConfig("https://testnet.binancefuture.com", "key", "secret")
    )
    calls = {"time": 0, "request": None}

    def fake_get(url, **kwargs):
        calls["time"] += 1
        assert url.endswith("/fapi/v1/time")
        return Response({"serverTime": 1_700_000_010_000})

    def fake_request(method, url, params=None, timeout=None):
        calls["request"] = dict(method=method, url=url, params=dict(params or {}))
        return Response({"status": "NEW", "orderId": 1, "clientOrderId": "x"})

    monkeypatch.setattr(adapter.session, "get", fake_get)
    monkeypatch.setattr(adapter.session, "request", fake_request)
    monkeypatch.setattr("app.mm.binance_execution.time.time", lambda: 1_700_000_000.0)
    monkeypatch.setattr("app.mm.binance_execution.time.monotonic", lambda: 10.0)

    adapter._signed_request("GET", "/fapi/v1/openOrders", {"symbol": "BTCUSDT"})
    assert calls["time"] == 1
    assert calls["request"]["params"]["timestamp"] == 1_700_000_010_000


def test_server_time_sync_failure_is_fail_closed(monkeypatch):
    adapter = BinanceUSDMExecutionAdapter(
        BinanceExecutionConfig("https://testnet.binancefuture.com", "key", "secret")
    )

    def fake_get(_url, **_kwargs):
        raise RuntimeError("clock endpoint unavailable")

    monkeypatch.setattr(adapter.session, "get", fake_get)
    try:
        adapter._signed_request("GET", "/fapi/v1/openOrders", {"symbol": "BTCUSDT"})
    except RuntimeError as exc:
        assert str(exc) == "clock endpoint unavailable"
    else:
        raise AssertionError("signed request proceeded without server-time synchronization")
