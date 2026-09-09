import json

from app.v19.config import load_v19_config
from app.v19.replay import prepare_l2_dataset


def test_replay_ignores_future_events_for_features(tmp_path):
    events = tmp_path / "events.jsonl"
    rows = []
    for i in range(12):
        rows.append({
            "type": "depth", "ts_ms": i * 100, "bids": [[100.0 + i * 0.01, 10.0]],
            "asks": [[100.1 + i * 0.01, 8.0]],
        })
        rows.append({
            "type": "trade", "ts_ms": i * 100 + 10, "price": 100.05 + i * 0.01,
            "qty": 1.0, "buyer_is_maker": False,
        })
    events.write_text("\n".join(json.dumps(x) for x in rows))
    X, returns, fills, timestamps = prepare_l2_dataset(events, 200_000_000)
    assert len(X) == len(returns) == len(fills) == len(timestamps)
    assert len(X) > 0


def test_replay_reconstructs_binance_t_depth_snap_set_delta(tmp_path):
    events = tmp_path / "binance_t_depth.jsonl"
    rows = [
        {"type": "depth", "ts_ms": 0, "update_type": "snap", "side": "b", "price": 100.0, "qty": 5.0},
        {"type": "depth", "ts_ms": 0, "update_type": "snap", "side": "b", "price": 99.9, "qty": 4.0},
        {"type": "depth", "ts_ms": 0, "update_type": "snap", "side": "a", "price": 100.1, "qty": 6.0},
        {"type": "depth", "ts_ms": 0, "update_type": "snap", "side": "a", "price": 100.2, "qty": 7.0},
        {"type": "depth", "ts_ms": 100, "update_type": "delta", "side": "b", "price": 100.0, "qty": 2.0},
        {"type": "depth", "ts_ms": 100, "update_type": "set", "side": "a", "price": 100.1, "qty": 3.0},
        {"type": "depth", "ts_ms": 100, "update_type": "delta", "side": "b", "price": 99.8, "qty": 1.5},
        {"type": "trade", "ts_ms": 110, "price": 100.1, "qty": 0.5, "buyer_is_maker": False},
        {"type": "depth", "ts_ms": 200, "update_type": "set", "side": "b", "price": 100.0, "qty": 0.0},
    ]
    events.write_text("\n".join(json.dumps(x) for x in rows))

    X, returns, fills, timestamps = prepare_l2_dataset(events, 100_000_000)

    assert len(X) > 0
    assert len(X) == len(returns) == len(fills) == len(timestamps)
    assert timestamps[0] == 0
