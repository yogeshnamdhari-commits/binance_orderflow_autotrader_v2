import json
from pathlib import Path

import pytest

from app.mm.config import V20Config
from scripts.v20_event_backtest_capture import load_events, load_snapshot


def _write_capture(root: Path) -> Path:
    capture = root / "capture"
    capture.mkdir()
    (capture / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "v10.raw.v1",
                "symbol": "BTCUSDT",
                "session_id": "test-session",
                "event_count": 2,
                "bootstrap": {"status": "BRIDGED"},
            }
        ),
        encoding="utf-8",
    )
    (capture / "snapshot.json").write_text(
        json.dumps(
            {
                "E": 1_000,
                "T": 1_000,
                "lastUpdateId": 10,
                "bids": [["99.0", "10"]],
                "asks": [["101.0", "10"]],
            }
        ),
        encoding="utf-8",
    )
    rows = [
        {
            "receive_ns": 1_100_000_000,
            "stream": "btcusdt@depth@100ms",
            "event_type": "depthUpdate",
            "event_time_ms": 1_100,
            "raw_json": json.dumps(
                {
                    "stream": "btcusdt@depth@100ms",
                    "data": {
                        "e": "depthUpdate",
                        "E": 1_100,
                        "U": 10,
                        "u": 11,
                        "pu": 9,
                        "b": [],
                        "a": [],
                    },
                }
            ),
        },
        {
            "receive_ns": 1_200_000_000,
            "stream": "btcusdt@trade",
            "event_type": "trade",
            "event_time_ms": 1_200,
            "raw_json": json.dumps(
                {
                    "stream": "btcusdt@trade",
                    "data": {
                        "e": "trade",
                        "E": 1_200,
                        "p": "99.70",
                        "q": "1.0",
                        "t": 1,
                        "m": True,
                    },
                }
            ),
        },
    ]
    (capture / "events.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    return capture


def test_local_capture_loader_reconstructs_v20_events(tmp_path):
    capture = _write_capture(tmp_path)

    snapshot = load_snapshot(capture)
    depth, trades, counts = load_events(capture)

    assert snapshot.last_update_id == 10
    assert len(depth) == 1
    assert depth[0].prev_final_update_id == 10
    assert depth[0].final_update_id == 11
    assert len(trades) == 1
    assert trades[0].aggressor_side.value == "SELL"
    assert counts == {"raw_rows": 2, "depth_events": 1, "trade_events": 1}


def test_loader_reports_one_depth_sequence_gap_without_cascading(tmp_path):
    capture = _write_capture(tmp_path)
    manifest = json.loads((capture / "manifest.json").read_text(encoding="utf-8"))
    manifest["event_count"] = 3
    (capture / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    rows = [
        json.loads(line)
        for line in (capture / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    rows.insert(
        1,
        {
            "receive_ns": 1_150_000_000,
            "stream": "btcusdt@depth@100ms",
            "event_type": "depthUpdate",
            "event_time_ms": 1_150,
            "raw_json": json.dumps(
                {
                    "stream": "btcusdt@depth@100ms",
                    "data": {
                        "e": "depthUpdate",
                        "E": 1_150,
                        "U": 20,
                        "u": 21,
                        "pu": 19,
                        "b": [],
                        "a": [],
                    },
                }
            ),
        },
    )
    (capture / "events.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="depth sequence gap.*expected_prev=11"):
        load_events(capture)


def test_config_loader_keeps_exact_candidate_hash_contract():
    config = V20Config.from_json("app/mm/config_backtest_toxicity_v1.json")
    assert config.symbol == "BTCUSDT"
    assert config.live_order_submission is False
    assert config.toxicity_filter_enabled is True
