from app.v10_parity import compare_replay_states


def test_identical_states_pass_parity():
    a = {"best_bid": "100.0", "best_ask": "100.1", "bid_depth": "5", "ask_depth": "7"}
    result = compare_replay_states(a, a)
    assert result["pass"] is True
    assert result["mismatches"] == []


def test_material_state_difference_fails_parity():
    replay = {"best_bid": "100.0", "best_ask": "100.1", "bid_depth": "5", "ask_depth": "7"}
    reference = {"best_bid": "99.9", "best_ask": "100.1", "bid_depth": "5", "ask_depth": "7"}
    result = compare_replay_states(replay, reference)
    assert result["pass"] is False
    assert "best_bid" in result["mismatches"]


def test_unexpected_keys_are_reported():
    result = compare_replay_states({"best_bid": "100"}, {"best_bid": "100", "best_ask": "101"})
    assert result["pass"] is False
    assert "best_ask" in result["mismatches"]
