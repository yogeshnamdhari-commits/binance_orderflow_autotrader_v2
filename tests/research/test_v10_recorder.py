from urllib.parse import parse_qs, urlsplit

from app.v10_recorder import V10Recorder


def test_build_stream_url_uses_combined_stream_format():
    recorder = V10Recorder("BTCUSDT", "/tmp/v10", "wss://fstream.binance.com", ["btcusdt@depth@100ms", "btcusdt@trade"])
    url = recorder.build_stream_url()
    assert "/stream?streams=" in url
    assert "btcusdt@depth@100ms" in url
    assert "btcusdt@trade" in url


def test_handle_message_updates_diagnostics_without_transforming_raw_event(tmp_path):
    recorder = V10Recorder("BTCUSDT", tmp_path, "wss://example.invalid/stream", ["btcusdt@depth@100ms"])
    recorder.start(start_ns=1)
    recorder.handle_message('{"stream":"btcusdt@depth@100ms","data":{"e":"depthUpdate","E":1000,"U":101,"u":110,"pu":100}}', receive_ns=2)
    recorder.handle_message('{"stream":"btcusdt@depth@100ms","data":{"e":"depthUpdate","E":1100,"U":111,"u":120,"pu":110}}', receive_ns=3)
    assert recorder.diagnostics()["depth_events"] == 2
    assert recorder.diagnostics()["gaps"] == 0
    recorder.close(end_ns=4)


def test_reconnect_starts_new_depth_continuity_segment(tmp_path):
    recorder = V10Recorder("BTCUSDT", tmp_path, "wss://example.invalid/stream", ["btcusdt@depth@100ms"])
    recorder.start(start_ns=1)
    recorder.handle_message('{"stream":"btcusdt@depth@100ms","data":{"e":"depthUpdate","E":1000,"U":101,"u":110,"pu":100}}', receive_ns=2)
    recorder.mark_reconnect()
    recorder.handle_message('{"stream":"btcusdt@depth@100ms","data":{"e":"depthUpdate","E":2000,"U":500,"u":510,"pu":499}}', receive_ns=3)
    assert recorder.diagnostics()["reconnect_boundaries"] == 1
    assert recorder.diagnostics()["gaps"] == 0
    recorder.close(end_ns=4)
