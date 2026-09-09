from app.v19.gate import evaluate_gate, run_cost_stress


def test_gate_rejects_negative_regime():
    result = evaluate_gate(
        [1.0, 1.2, 0.8],
        [0.9, 1.0, 0.7],
        [0.9, 1.1, 0.7],
        [[1.0, 1.2], [-0.5]],
        {1.0: 0.5},
    )
    assert not result.passed
    assert any("regime" in reason for reason in result.reasons)


def test_cost_stress_is_monotonic():
    result = run_cost_stress([2.0, 2.0], [1.0, 1.25])
    assert result[1.0] > result[1.25]
