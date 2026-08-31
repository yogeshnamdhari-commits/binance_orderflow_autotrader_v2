from app.v10_book_replay import V10BookReplay, ReplayStatus


def test_replay_requires_snapshot_continuity_and_applies_depth_updates():
    replay = V10BookReplay()
    snapshot = {"lastUpdateId": 100, "bids": [[100, 2]], "asks": [[101, 3]]}
    events = [
        {"e": "depthUpdate", "U": 99, "u": 100, "pu": 98, "b": [], "a": []},
        {"e": "depthUpdate", "U": 101, "u": 105, "pu": 100, "b": [[100, "1"]], "a": [[102, "2"]]},
        {"e": "depthUpdate", "U": 106, "u": 110, "pu": 105, "b": [[99, "4"]], "a": [[101, "0"]]},
    ]
    result = replay.replay(snapshot, events)
    assert result.status == ReplayStatus.OK
    assert result.last_update_id == 110
    assert result.bids == {100: 1, 99: 4}
    assert result.asks == {102: 2}


def test_replay_rejects_pu_gap():
    replay = V10BookReplay()
    snapshot = {"lastUpdateId": 100, "bids": [[100, 2]], "asks": [[101, 3]]}
    events = [
        {"e": "depthUpdate", "U": 101, "u": 105, "pu": 100, "b": [], "a": []},
        {"e": "depthUpdate", "U": 106, "u": 110, "pu": 104, "b": [], "a": []},
    ]
    result = replay.replay(snapshot, events)
    assert result.status == ReplayStatus.GAP
    assert result.reason == "PU_MISMATCH"


def test_replay_rejects_first_event_that_does_not_bridge_snapshot():
    replay = V10BookReplay()
    snapshot = {"lastUpdateId": 100, "bids": [[100, 2]], "asks": [[101, 3]]}
    result = replay.replay(snapshot, [{"U": 105, "u": 110, "pu": 104, "b": [], "a": []}])
    assert result.status == ReplayStatus.NO_BRIDGING_EVENT
    assert result.reason == "FIRST_EVENT_DOES_NOT_BRIDGE_SNAPSHOT"


def test_replay_skips_events_already_covered_by_snapshot():
    replay = V10BookReplay()
    snapshot = {"lastUpdateId": 100, "bids": [[100, 2]], "asks": [[101, 3]]}
    result = replay.replay(snapshot, [
        {"U": 90, "u": 100, "pu": 89, "b": [[100, 9]], "a": []},
        {"U": 99, "u": 105, "pu": 100, "b": [[100, 1]], "a": []},
    ])
    assert result.status == ReplayStatus.OK
    assert result.last_update_id == 105
    assert result.bids == {100: 1}
