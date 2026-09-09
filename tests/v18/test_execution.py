import pytest

from app.v18.execution import ExecutionCost, stressed_cost


def test_round_trip_costs_are_explicit():
    cost = ExecutionCost(0.2, 0.5, 0.4, 0.1, 0.3)
    assert cost.maker_round_trip_bps == pytest.approx(0.9)
    assert cost.taker_round_trip_bps == pytest.approx(1.5)


def test_cost_stress_scales_all_components():
    cost = ExecutionCost(0.2, 0.5, 0.4, 0.1, 0.3)
    stressed = stressed_cost(cost, 1.5)
    assert stressed.spread_bps == pytest.approx(0.6)
    assert stressed.non_fill_opportunity_bps == pytest.approx(0.45)
