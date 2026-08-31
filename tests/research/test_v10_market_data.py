from app.v10_market_data import DepthSequenceValidator, normalize_ws_event, SessionRecorder


def test_depth_sequence_accepts_first_event_and_contiguous_updates():
    validator = DepthSequenceValidator()
    first = validator.observe({"e": "depthUpdate", "E": 1000, "U": 101, "u": 110, "pu": 100})
    second = validator.observe({"e": "depthUpdate", "E": 1100, "U": 111, "u": 120, "pu": 110})
    assert first.state == "FIRST"
    assert second.state == "CONTIGUOUS"
    assert second.previous_u == 110


def test_depth_sequence_rejects_gap_and_does_not_hide_it():
    validator = DepthSequenceValidator()
    validator.observe({"e": "depthUpdate", "E": 1000, "U": 101, "u": 110, "pu": 100})
    result = validator.observe({"e": "depthUpdate", "E": 1200, "U": 121, "u": 130, "pu": 120})
    assert result.state == "GAP"
    assert result.reason == "PU_MISMATCH"


def test_normalize_preserves_raw_payload_and_adds_receive_metadata():
    raw = '{"stream":"btcusdt@trade","data":{"e":"trade","E":123,"T":122,"p":"100.1","q":"2"}}'
    normalized = normalize_ws_event(raw, receive_ns=999)
    assert normalized.stream == "btcusdt@trade"
    assert normalized.event_type == "trade"
    assert normalized.event_time_ms == 123
    assert normalized.receive_time_ns == 999
    assert normalized.raw_json == raw


def test_session_recorder_writes_raw_event_and_manifest(tmp_path):
    recorder = SessionRecorder(tmp_path, "BTCUSDT", ["btcusdt@depth@100ms", "btcusdt@trade"])
    recorder.start(start_ns=1_000_000)
    raw = '{"stream":"btcusdt@trade","data":{"e":"trade","E":123}}'
    recorder.record_raw(raw, receive_ns=2_000_000)
    recorder.close(end_ns=3_000_000)

    session_dirs = list(tmp_path.iterdir())
    assert len(session_dirs) == 1
    import json
    manifest = json.loads((session_dirs[0] / "manifest.json").read_text())
    assert manifest["symbol"] == "BTCUSDT"
    assert manifest["start_ns"] == 1_000_000
    assert manifest["end_ns"] == 3_000_000

    rows = [json.loads(line) for line in (session_dirs[0] / "events.jsonl").read_text().splitlines()]
    assert rows[0]["raw_json"] == raw
    assert rows[0]["receive_ns"] == 2_000_000
