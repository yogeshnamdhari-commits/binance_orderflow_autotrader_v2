from app.v19.config import V19Config
from app.v19.gate import evaluate_gate, run_cost_stress


def _config():
    return V19Config(
        symbol="BTCUSDT",
        prediction_horizon_ms=1000,
        feature_names=("queue_imbalance_1",),
        min_train_events=1,
        min_test_events=1,
        embargo_events=0,
        max_feature_age_ms=1000,
        maker_round_trip_cost_bps=1.0,
        taker_round_trip_cost_bps=2.0,
        non_fill_opportunity_cost_bps=0.5,
        maker_share=1.0,
        cost_stress_multipliers=(1.0, 1.25),
        live_order_submission=False,
        config_hash="test",
    )


def test_gate_rejects_negative_regime():
    result = evaluate_gate([1.0, 1.2, 0.8], [0.9, 1.0, 0.7], [1.0, 1.2, -0.5], [[1.0, 1.2], [-0.5]], {1.0: 0.5})
    assert not result.passed
    assert any("regime" in reason for reason in result.reasons)


def test_cost_stress_is_monotonic():
    result = run_cost_stress([2.0, 2.0], [0.8, 0.8], _config())
    assert result[1.0] > result[1.25]
