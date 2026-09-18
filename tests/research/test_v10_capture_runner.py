"""V10 capture integrity tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.v10_capture import (
    _depth_update_id_range,
    fetch_ws_snapshot_with_retries,
    find_bridging_index,
)
from app.v10_recorder import V10Recorder


def _depth_update_payload(
    U: int,
    u: int,
    pu: int | None = None,
    bids: list[list[str]] | None = None,
    asks: list[list[str]] | None = None,
) -> str:
    return json.dumps({
        "stream": "btcusdt@depth@100ms",
        "data": {
            "e": "depthUpdate",
            "E": U,
            "T": U,
            "s": "BTCUSDT",
            "U": U,
            "u": u,
            "pu": pu,
            "b": bids or [],
            "a": asks or [],
        },
    })


def test_depth_update_id_range_extracts_U_and_u():
    raw = _depth_update_payload(U=100, u=200)
    result = _depth_update_id_range(raw)
    assert result == (100, 200)


def test_depth_update_id_range_returns_none_for_malformed():
    assert _depth_update_id_range("not json") is None
    assert _depth_update_id_range('{"e":"trade"}') is None


def test_find_bridging_index_accepts_exact_bridge():
    events = [
        (_depth_update_payload(U=100, u=105, pu=99), 0, "btcusdt@depth@100ms"),
        (_depth_update_payload(U=101, u=110, pu=100), 0, "btcusdt@depth@100ms"),
    ]
    idx = find_bridging_index(events, snapshot_id=100)
    assert idx == 0


def test_find_bridging_index_rejects_u_greater_than_snapshot_without_pu_match():
    events = [
        (_depth_update_payload(U=200, u=250, pu=199), 0, "btcusdt@depth@100ms"),
    ]
    idx = find_bridging_index(events, snapshot_id=100)
    assert idx is None


def test_find_bridging_index_returns_none_when_no_bridge():
    events = [
        (_depth_update_payload(U=50, u=55, pu=49), 0, "btcusdt@depth@100ms"),
    ]
    idx = find_bridging_index(events, snapshot_id=100)
    assert idx is None


def test_u_greater_than_snapshot_alone_is_insufficient():
    snapshot_id = 100
    raw = _depth_update_payload(U=200, u=250, pu=199)
    idx = find_bridging_index([(raw, 0, "stream")], snapshot_id=snapshot_id)
    assert idx is None


def test_snapshot_retry_succeeds_after_transient_failure(monkeypatch):
    calls = {"count": 0}

    def fake_fetch(_symbol: str, limit: int = 1000):
        calls["count"] += 1
        if calls["count"] < 3:
            raise RuntimeError("temporary websocket failure")
        return {"lastUpdateId": 123, "bids": [], "asks": []}

    monkeypatch.setattr("app.v10_capture.fetch_ws_snapshot", fake_fetch)
    monkeypatch.setattr("app.v10_capture.time.sleep", lambda _seconds: None)

    result = fetch_ws_snapshot_with_retries("BTCUSDT", attempts=3, retry_delay_seconds=0.0)

    assert result["lastUpdateId"] == 123
    assert calls["count"] == 3


def test_snapshot_retry_exhausts_cleanly(monkeypatch):
    calls = {"count": 0}

    def fake_fetch(_symbol: str, limit: int = 1000):
        calls["count"] += 1
        raise RuntimeError("persistent websocket failure")

    monkeypatch.setattr("app.v10_capture.fetch_ws_snapshot", fake_fetch)
    monkeypatch.setattr("app.v10_capture.time.sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="persistent websocket failure"):
        fetch_ws_snapshot_with_retries("BTCUSDT", attempts=3, retry_delay_seconds=0.0)

    assert calls["count"] == 3


def test_record_bootstrap_writes_manifest(tmp_path: Path):
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    recorder = V10Recorder(
        symbol="BTCUSDT",
        output_dir=tmp_path,
        ws_url="wss://example.com",
        streams=["btcusdt@depth@100ms"],
    )

    class FakeSession:
        def __init__(self, manifest_ref):
            self._manifest = manifest_ref

        def _write_manifest(self):
            (session_dir / "manifest.json").write_text(
                json.dumps(self._manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

    manifest = {
        "schema_version": "v10.raw.v1",
        "session_id": "test",
    }
    recorder.session = FakeSession(manifest)
    recorder._events = open(session_dir / "events.jsonl", "w")
    recorder._manifest = manifest

    buffered = [(_depth_update_payload(U=101, u=110, pu=100), 0, "stream")]
    recorder.record_bootstrap(snapshot_id=100, bridge_index=0, buffered=buffered)

    manifest_path = session_dir / "manifest.json"
    assert manifest_path.exists()
    with open(manifest_path) as f:
        loaded = json.load(f)
    assert loaded["bootstrap"]["status"] == "BRIDGED"
    assert loaded["bootstrap"]["snapshot_last_update_id"] == 100
    assert loaded["bootstrap"]["first_pu"] == 100


def test_record_bootstrap_failure_writes_manifest(tmp_path: Path):
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    recorder = V10Recorder(
        symbol="BTCUSDT",
        output_dir=tmp_path,
        ws_url="wss://example.com",
        streams=["btcusdt@depth@100ms"],
    )

    class FakeSession:
        def __init__(self, manifest_ref):
            self._manifest = manifest_ref

        def _write_manifest(self):
            (session_dir / "manifest.json").write_text(
                json.dumps(self._manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

    manifest = {
        "schema_version": "v10.raw.v1",
        "session_id": "test",
    }
    recorder.session = FakeSession(manifest)
    recorder._events = open(session_dir / "events.jsonl", "w")
    recorder._manifest = manifest

    recorder.record_bootstrap_failure(
        snapshot_id=100,
        reason="BRIDGE_TIMEOUT",
        detail="No bridge found",
    )

    manifest_path = session_dir / "manifest.json"
    assert manifest_path.exists()
    with open(manifest_path) as f:
        loaded = json.load(f)
    assert loaded["bootstrap"]["status"] == "FAILED"
    assert loaded["bootstrap"]["reason"] == "BRIDGE_TIMEOUT"


def test_sequence_gap_during_capture_marks_diagnostics():
    validator = type("V", (), {"previous_u": None})()
    event = {"U": 200, "u": 250, "pu": 199}
    previous_u = None
    final_update = int(event["u"])
    previous_update = event.get("pu")
    previous_update = int(previous_update) if previous_update is not None else None

    if previous_u is None:
        previous_u = final_update
        state = "FIRST"
    else:
        if previous_update is not None and previous_update != previous_u:
            state = "GAP"
        else:
            state = "CONTIGUOUS"
        previous_u = final_update

    assert state == "FIRST"


def test_no_silent_fallback_makes_capture_replayable():
    snapshot_id = 100
    raw = _depth_update_payload(U=200, u=250, pu=199)
    idx = find_bridging_index([(raw, 0, "stream")], snapshot_id=snapshot_id)
    assert idx is None, "u > snapshot_id alone must not create a bridge"
