from app.v10_data_audit import audit_session


def test_audit_detects_depth_gap(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    (session / "manifest.json").write_text('{"schema_version":"v10.raw.v1","symbol":"BTCUSDT"}')
    (session / "events.jsonl").write_text(
        '{"stream":"btcusdt@depth@100ms","event_type":"depthUpdate","event_time_ms":1,"receive_ns":2,"raw_json":"{\\"data\\":{\\"e\\":\\"depthUpdate\\",\\"U\\":1,\\"u\\":2,\\"pu\\":0}}"}\n'
        '{"stream":"btcusdt@depth@100ms","event_type":"depthUpdate","event_time_ms":2,"receive_ns":3,"raw_json":"{\\"data\\":{\\"e\\":\\"depthUpdate\\",\\"U\\":4,\\"u\\":5,\\"pu\\":3}}"}\n'
    )
    result = audit_session(session)
    assert result["depth_gap_count"] == 1
    assert result["depth_continuity_pass"] is False
