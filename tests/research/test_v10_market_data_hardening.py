import json
from app.v10_market_data import DepthSequenceValidator, normalize_ws_event
from app.v10_data_audit import audit_session


def test_sequence_validator_does_not_treat_normal_overlapping_update_as_gap():
    v = DepthSequenceValidator()
    assert v.observe({"U": 100, "u": 105}).state == "FIRST"
    assert v.observe({"U": 103, "u": 110}).state == "CONTIGUOUS"


def test_sequence_validator_rejects_regression():
    v = DepthSequenceValidator()
    v.observe({"U": 100, "u": 105})
    assert v.observe({"U": 106, "u": 104}).state == "MALFORMED"


def test_audit_flags_duplicate_raw_payload(tmp_path):
    session = tmp_path / "s"
    session.mkdir()
    (session / "manifest.json").write_text(json.dumps({"schema_version":"v10.raw.v1","symbol":"BTCUSDT"}))
    raw = '{"stream":"btcusdt@trade","data":{"e":"trade","E":1000}}'
    rows = [
        {"stream":"btcusdt@trade","event_type":"trade","receive_ns":1,"event_time_ms":1000,"raw_json":raw},
        {"stream":"btcusdt@trade","event_type":"trade","receive_ns":2,"event_time_ms":1001,"raw_json":raw},
    ]
    (session / "events.jsonl").write_text("\n".join(json.dumps(x) for x in rows) + "\n")
    result = audit_session(session)
    assert result["duplicate_raw_count"] == 1
    assert result["overall_pass"] is False
