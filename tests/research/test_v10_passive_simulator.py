import pytest
from app.v10_passive_simulator import simulate_passive_order


def test_simulator_accounts_for_partial_fill_and_economic_terms():
    result = simulate_passive_order(
        fill_fraction=0.5,
        spread_capture_bps=4.0,
        fee_rebate_bps=0.2,
        adverse_selection_bps=1.0,
        inventory_cost_bps=0.3,
        exit_cost_bps=0.8,
        cancellation_cost_bps=0.1,
    )
    assert result["filled_fraction"] == 0.5
    assert result["net_ev_bps"] == pytest.approx(0.95)


def test_unfilled_order_only_pays_cancellation_cost():
    result = simulate_passive_order(0.0, 4.0, 0.2, 1.0, 0.3, 0.8, 0.1)
    assert result["net_ev_bps"] == -0.1
