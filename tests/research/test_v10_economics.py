from app.v10_economics import passive_order_ev_bps


def test_positive_ev_requires_fill_probability_and_all_cost_terms():
    result = passive_order_ev_bps(
        fill_probability=0.5,
        spread_capture_bps=8.0,
        fee_rebate_bps=1.0,
        adverse_selection_bps=2.0,
        inventory_cost_bps=1.0,
        exit_cost_bps=1.0,
        cancellation_cost_bps=0.5,
    )
    assert result == 2.0


def test_zero_fill_probability_has_non_positive_ev():
    assert passive_order_ev_bps(0.0, 100.0, 1.0, 0.0, 0.0, 0.0, 0.0) == 0.0
