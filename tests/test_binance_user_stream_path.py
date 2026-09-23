from app.mm.binance_user_stream import BinanceUSDMUserStream


def test_user_stream_uses_listen_key_path(monkeypatch):
    stream = BinanceUSDMUserStream(
        api_key="key",
        control_url="wss://ws-fapi.binance.com/ws-fapi/v1",
        private_stream_base="wss://fstream.binance.com/private/ws",
    )
    stream.listen_key = "ABC123"
    captured = {}

    class FakeWebSocketApp:
        def __init__(self, url, **_kwargs):
            captured["url"] = url
        def run_forever(self, **_kwargs):
            stream.stop_flag = True

    monkeypatch.setattr("app.mm.binance_user_stream.websocket.WebSocketApp", FakeWebSocketApp)
    monkeypatch.setattr(stream, "start_stream", lambda: "ABC123")
    stream.run()

    assert captured["url"] == "wss://fstream.binance.com/private/ws/ABC123"


def test_demo_order_base_selects_testnet_user_stream(monkeypatch):
    monkeypatch.setenv("BINANCE_ORDER_BASE_URL", "https://demo-fapi.binance.com")
    stream = BinanceUSDMUserStream(api_key="key")
    assert stream.control_url == "wss://testnet.binancefuture.com/ws-fapi/v1"
    assert stream.private_stream_base == "wss://stream.binancefuture.com/private/ws"
