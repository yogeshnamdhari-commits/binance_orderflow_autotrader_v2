from app.v19.features import L2Event, compute_orderflow_features, feature_names


def test_future_event_cannot_change_features():
    past = [L2Event(1, 100, 10, 101, 8, "BUY", 2)]
    future = L2Event(3, 100, 1000, 101, 1, "SELL", 999)
    assert compute_orderflow_features(past, 2) == compute_orderflow_features(past + [future], 2)


def test_feature_order_is_deterministic():
    assert feature_names() == (
        "queue_imbalance_1", "queue_imbalance_3", "ofi_1", "ofi_3",
        "signed_trade_flow", "spread_bps", "depth_concentration",
        "queue_change_intensity", "liquidity_state",
    )


def test_multilevel_depth_is_used():
    event = L2Event(
        1, 100, 10, 101, 5, bid_levels=((100, 10), (99.9, 30), (99.8, 20)),
        ask_levels=((101, 5), (101.1, 5), (101.2, 5)),
    )
    features = compute_orderflow_features([event], 1)
    assert features["queue_imbalance_3"] > features["queue_imbalance_1"]
