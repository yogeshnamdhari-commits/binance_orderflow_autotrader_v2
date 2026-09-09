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
