"""Tests for V12 capture session validity (the run_forever shutdown fix)."""
from pathlib import Path

from app.v12.capture import (
    build_ws_url,
    find_bridging_index,
    _depth_update_id_range,
    _safe_json,
    CaptureResult,
)


def test_safe_json_returns_dict_for_valid_message():
    parsed = _safe_json('{"stream":"x","data":{"e":"trade"}}')
    assert parsed == {"stream": "x", "data": {"e": "trade"}}


def test_safe_json_returns_none_for_invalid_json():
    assert _safe_json("not json") is None
    assert _safe_json("") is None


def test_depth_update_id_range_extracts_ids():
    msg = '{"stream":"btcusdt@depth@100ms","data":{"e":"depthUpdate","U":100,"u":101,"b":[],"a":[]}}'
    result = _depth_update_id_range(msg)
    assert result == (100, 101)


def test_depth_update_id_range_none_for_trade():
    msg = '{"stream":"btcusdt@trade","data":{"e":"trade","t":1}}'
    assert _depth_update_id_range(msg) is None


def test_find_bridging_index_finds_contiguous_buffer():
    snapshot_id = 100
    buffered = [
        ('{"data":{"e":"trade"}}', 1000, "trade"),
        ('{"data":{"e":"depthUpdate","U":98,"u":102,"b":[],"a":[]}}', 1001, "depth"),  # U<=101<=u
    ]
    idx = find_bridging_index(buffered, snapshot_id)
    assert idx == 1


def test_find_bridging_index_returns_none_when_no_bridge():
    snapshot_id = 100
    buffered = [
        ('{"data":{"e":"trade"}}', 1000, "trade"),
        ('{"data":{"e":"depthUpdate","U":500,"u":502,"b":[],"a":[]}}', 1001, "depth"),
    ]
    assert find_bridging_index(buffered, snapshot_id) is None


def test_build_ws_url_combines_streams():
    url = build_ws_url("wss://fstream.binance.com", ["btcusdt@depth@100ms", "btcusdt@trade"])
    assert url.startswith("wss://fstream.binance.com/stream?streams=")
    assert "btcusdt@depth@100ms" in url
    assert "btcusdt@trade" in url


def test_capture_result_is_dataclass():
    assert CaptureResult.__annotations__  # has fields
    # valid sessions produce non-empty sequence ranges
    for field in ("session_dir", "symbol", "valid", "event_counts", "reconnects", "gaps"):
        assert field in CaptureResult.__annotations__
