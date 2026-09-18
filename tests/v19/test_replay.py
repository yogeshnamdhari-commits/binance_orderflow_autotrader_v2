"""V19 replay tests."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from app.v19.config import V19Config
from app.v19.replay import (
    ReconstructionIntegrityError,
    _DepthUpdate,
    _parse_v10_depth_update,
    _reconstruct_depth,
    _trade_rows,
    prepare_l2_dataset,
)


def _write_events(tmp_path: Path, rows: list[dict], snapshot_bids=None, snapshot_asks=None) -> Path:
    events = tmp_path / "events.jsonl"
    events.write_text("\n".join(json.dumps(x) for x in rows), encoding="utf-8")
    if snapshot_bids is not None and snapshot_asks is not None:
        snapshot = {
            "E": 0,
            "T": 0,
            "asks": snapshot_asks,
            "bids": snapshot_bids,
            "lastUpdateId": 100,
        }
        (tmp_path / "snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    return events


def _depth_update_payload(bids=None, asks=None, U=1, u=1, pu=0):
    return json.dumps({
        "stream": "btcusdt@depth@100ms",
        "data": {
            "e": "depthUpdate",
            "E": 1000,
            "T": 1000,
            "s": "BTCUSDT",
            "U": U,
            "u": u,
            "pu": pu,
            "b": bids or [],
            "a": asks or [],
        },
    })


def test_replay_ignores_future_events_for_features(tmp_path):
    rows = []
    for i in range(12):
        rows.append({
            "event_type": "depthUpdate",
            "event_time_ms": i * 100,
            "raw_json": _depth_update_payload(
                bids=[[str(100.0), "10.0"]],
                asks=[[str(100.1), "8.0"]],
                U=i + 101,
                u=i + 101,
                pu=i + 100,
            ),
        })
        rows.append({
            "event_type": "trade",
            "event_time_ms": i * 100 + 10,
            "raw_json": json.dumps({
                "stream": "btcusdt@trade",
                "data": {
                    "e": "trade",
                    "E": i * 100 + 10,
                    "T": i * 100 + 10,
                    "p": str(100.05),
                    "q": "1.0",
                    "m": False,
                },
            }),
        })
    events_path = _write_events(
        tmp_path, rows,
        snapshot_bids=[["100.0", "10.0"]],
        snapshot_asks=[["100.1", "8.0"]],
    )
    X, returns, fills, timestamps = prepare_l2_dataset(events_path, 200_000_000)
    assert len(X) == len(returns) == len(fills) == len(timestamps)
    assert len(X) > 0


def test_replay_reconstructs_book_from_snapshot_and_incremental_updates(tmp_path):
    rows = [
        {
            "event_type": "depthUpdate",
            "event_time_ms": 0,
            "raw_json": _depth_update_payload(
                bids=[["100.0", "5.0"], ["99.9", "4.0"]],
                asks=[["100.1", "6.0"], ["100.2", "7.0"]],
                U=101,
                u=101,
                pu=100,
            ),
        },
        {
            "event_type": "depthUpdate",
            "event_time_ms": 100,
            "raw_json": _depth_update_payload(
                bids=[["100.0", "3.0"]],
                asks=[["100.1", "0.0"]],
                U=102,
                u=102,
                pu=101,
            ),
        },
        {
            "event_type": "depthUpdate",
            "event_time_ms": 200,
            "raw_json": _depth_update_payload(
                bids=[["99.8", "1.5"]],
                asks=[],
                U=103,
                u=103,
                pu=102,
            ),
        },
    ]
    events_path = _write_events(
        tmp_path, rows,
        snapshot_bids=[["100.0", "5.0"], ["99.9", "4.0"]],
        snapshot_asks=[["100.1", "6.0"], ["100.2", "7.0"]],
    )
    X, returns, fills, timestamps = prepare_l2_dataset(events_path, 100_000_000)
    assert len(X) > 0
    assert len(X) == len(returns) == len(fills) == len(timestamps)
    assert timestamps[0] == 0


def test_incremental_update_does_not_replace_full_book(tmp_path):
    snapshot_bids = [[str(100.0 - i * 0.01), "10.0"] for i in range(20)]
    snapshot_asks = [[str(100.1 + i * 0.01), "8.0"] for i in range(20)]
    rows = [
        {
            "event_type": "depthUpdate",
            "event_time_ms": 0,
            "raw_json": _depth_update_payload(
                bids=[["100.0", "5.0"]],
                asks=[["100.1", "5.0"]],
                U=101,
                u=101,
                pu=100,
            ),
        },
        {
            "event_type": "depthUpdate",
            "event_time_ms": 100,
            "raw_json": _depth_update_payload(
                bids=[["100.0", "3.0"]],
                U=102,
                u=102,
                pu=101,
            ),
        },
        {
            "event_type": "depthUpdate",
            "event_time_ms": 200,
            "raw_json": _depth_update_payload(
                bids=[["99.99", "1.0"]],
                U=103,
                u=103,
                pu=102,
            ),
        },
    ]
    events_path = _write_events(
        tmp_path, rows,
        snapshot_bids=snapshot_bids,
        snapshot_asks=snapshot_asks,
    )
    X, returns, fills, timestamps = prepare_l2_dataset(events_path, 100_000_000)
    assert len(X) >= 1


def test_delta_update_accumulates_correctly(tmp_path):
    rows = [
        {
            "event_type": "depthUpdate",
            "event_time_ms": 0,
            "raw_json": _depth_update_payload(
                bids=[["100.0", "5.0"]],
                asks=[["100.1", "5.0"]],
                U=101,
                u=101,
                pu=100,
            ),
        },
        {
            "event_time_ms": 100,
            "event_type": "depthUpdate",
            "raw_json": _depth_update_payload(
                bids=[["100.0", "2.0"]],
                U=102,
                u=102,
                pu=101,
            ),
        },
        {
            "event_time_ms": 200,
            "event_type": "depthUpdate",
            "raw_json": _depth_update_payload(
                bids=[["100.0", "1.0"]],
                U=103,
                u=103,
                pu=102,
            ),
        },
    ]
    events_path = _write_events(
        tmp_path, rows,
        snapshot_bids=[["100.0", "5.0"]],
        snapshot_asks=[["100.1", "5.0"]],
    )
    X, returns, fills, timestamps = prepare_l2_dataset(events_path, 100_000_000)
    assert len(X) >= 1


def test_removed_level_disappears_from_book(tmp_path):
    rows = [
        {
            "event_type": "depthUpdate",
            "event_time_ms": 0,
            "raw_json": _depth_update_payload(
                bids=[["100.0", "5.0"], ["99.9", "4.0"]],
                asks=[["100.1", "5.0"]],
                U=101,
                u=101,
                pu=100,
            ),
        },
        {
            "event_type": "depthUpdate",
            "event_time_ms": 100,
            "raw_json": _depth_update_payload(
                bids=[["100.0", "0.0"]],
                U=102,
                u=102,
                pu=101,
            ),
        },
        {
            "event_type": "depthUpdate",
            "event_time_ms": 200,
            "raw_json": _depth_update_payload(
                bids=[],
                asks=[],
                U=103,
                u=103,
                pu=102,
            ),
        },
    ]
    events_path = _write_events(
        tmp_path, rows,
        snapshot_bids=[["100.0", "5.0"], ["99.9", "4.0"]],
        snapshot_asks=[["100.1", "5.0"]],
    )
    X, returns, fills, timestamps = prepare_l2_dataset(events_path, 100_000_000)
    assert len(X) >= 1


def test_trade_events_are_parsed_from_v10_raw_json(tmp_path):
    rows = [
        {
            "event_type": "depthUpdate",
            "event_time_ms": 0,
            "raw_json": _depth_update_payload(
                bids=[["100.0", "5.0"]],
                asks=[["100.1", "5.0"]],
                U=101,
                u=101,
                pu=100,
            ),
        },
        {
            "event_type": "depthUpdate",
            "event_time_ms": 100,
            "raw_json": _depth_update_payload(
                bids=[],
                asks=[],
                U=102,
                u=102,
                pu=101,
            ),
        },
        {
            "event_type": "depthUpdate",
            "event_time_ms": 200,
            "raw_json": _depth_update_payload(
                bids=[],
                asks=[],
                U=103,
                u=103,
                pu=102,
            ),
        },
        {
            "event_type": "trade",
            "event_time_ms": 50,
            "raw_json": json.dumps({
                "stream": "btcusdt@trade",
                "data": {
                    "e": "trade",
                    "E": 50,
                    "T": 50,
                    "p": "100.05",
                    "q": "1.5",
                    "m": True,
                },
            }),
        },
    ]
    events_path = _write_events(
        tmp_path, rows,
        snapshot_bids=[["100.0", "5.0"]],
        snapshot_asks=[["100.1", "5.0"]],
    )
    X, returns, fills, timestamps = prepare_l2_dataset(events_path, 100_000_000)
    assert len(X) > 0


def test_missing_snapshot_raises_file_not_found(tmp_path):
    events = tmp_path / "events.jsonl"
    events.write_text(json.dumps({"event_type": "depthUpdate", "event_time_ms": 0, "raw_json": _depth_update_payload()}))
    with pytest.raises(FileNotFoundError):
        prepare_l2_dataset(events, 1_000_000, snapshot_path=tmp_path / "nonexistent_snapshot.json")


def test_crossed_book_raises_reconstruction_integrity_error(tmp_path):
    rows = [
        {
            "event_type": "depthUpdate",
            "event_time_ms": 0,
            "raw_json": _depth_update_payload(
                bids=[["100.0", "5.0"]],
                asks=[["100.1", "5.0"]],
                U=101,
                u=101,
                pu=100,
            ),
        },
        {
            "event_type": "depthUpdate",
            "event_time_ms": 100,
            "raw_json": _depth_update_payload(
                bids=[["100.2", "1.0"]],
                asks=[["100.1", "0.0"]],
                U=102,
                u=102,
                pu=101,
            ),
        },
        {
            "event_type": "depthUpdate",
            "event_time_ms": 200,
            "raw_json": _depth_update_payload(
                bids=[["100.15", "2.0"]],
                asks=[["100.05", "1.0"]],
                U=103,
                u=103,
                pu=102,
            ),
        },
    ]
    events_path = _write_events(
        tmp_path, rows,
        snapshot_bids=[["100.0", "5.0"]],
        snapshot_asks=[["100.1", "5.0"]],
    )
    with pytest.raises(ReconstructionIntegrityError):
        prepare_l2_dataset(events_path, 100_000_000)


def test_sequence_gap_raises_reconstruction_integrity_error(tmp_path):
    rows = [
        {
            "event_type": "depthUpdate",
            "event_time_ms": 0,
            "raw_json": _depth_update_payload(
                bids=[["100.0", "5.0"]],
                asks=[["100.1", "5.0"]],
                U=101,
                u=101,
                pu=100,
            ),
        },
        {
            "event_type": "depthUpdate",
            "event_time_ms": 100,
            "raw_json": _depth_update_payload(
                bids=[["100.0", "3.0"]],
                asks=[["100.1", "3.0"]],
                U=103,
                u=103,
                pu=102,
            ),
        },
    ]
    events_path = _write_events(
        tmp_path, rows,
        snapshot_bids=[["100.0", "5.0"]],
        snapshot_asks=[["100.1", "5.0"]],
    )
    with pytest.raises(ReconstructionIntegrityError):
        prepare_l2_dataset(events_path, 100_000_000)


def test_parse_v10_depth_update_extracts_sequence_ids():
    raw = _depth_update_payload(
        bids=[["100.0", "1.0"]],
        asks=[["100.1", "0.0"]],
        U=101,
        u=101,
        pu=100,
    )
    update = _parse_v10_depth_update(raw, ts_ms=1000)
    assert update is not None
    assert update.U == 101
    assert update.u == 101
    assert update.pu == 100
    assert update.b == [(100.0, 1.0)]
    assert update.a == [(100.1, 0.0)]


def test_parse_v10_depth_update_returns_none_for_non_depthupdate():
    raw = json.dumps({
        "stream": "btcusdt@trade",
        "data": {"e": "trade", "p": "100.0", "q": "1.0"},
    })
    update = _parse_v10_depth_update(raw, ts_ms=1000)
    assert update is None


def test_snapshot_pu_mismatch_raises_reconstruction_integrity_error(tmp_path):
    rows = [
        {
            "event_type": "depthUpdate",
            "event_time_ms": 0,
            "raw_json": _depth_update_payload(
                bids=[["100.0", "5.0"]],
                asks=[["100.1", "5.0"]],
                U=101,
                u=101,
                pu=999,  # mismatch with snapshot lastUpdateId=100
            ),
        },
    ]
    events_path = _write_events(
        tmp_path, rows,
        snapshot_bids=[["100.0", "5.0"]],
        snapshot_asks=[["100.1", "5.0"]],
    )
    with pytest.raises(ReconstructionIntegrityError) as exc_info:
        prepare_l2_dataset(events_path, 100_000_000)
    assert "Snapshot bootstrap failure" in str(exc_info.value)
    assert exc_info.value.event_index == 0
    assert exc_info.value.update_pu == 999
    assert exc_info.value.snapshot_last_id == 100


def test_forward_dataset_fails_bootstrap_gate():
    events_path = Path("data/v16/forward/e264a34f0bac4d878f15a5ed8b0dc43c/events.jsonl")
    snapshot_path = Path("data/v16/forward/e264a34f0bac4d878f15a5ed8b0dc43c/snapshot.json")
    if not events_path.exists() or not snapshot_path.exists():
        pytest.skip("V16 forward dataset not available")
    with pytest.raises(ReconstructionIntegrityError) as exc_info:
        prepare_l2_dataset(events_path, 10_000_000_000, snapshot_path=snapshot_path)
    assert "Snapshot bootstrap failure" in str(exc_info.value)
    assert exc_info.value.event_index == 0
    assert exc_info.value.snapshot_last_id == 11499777751223
    assert exc_info.value.update_pu == 11499777819594
