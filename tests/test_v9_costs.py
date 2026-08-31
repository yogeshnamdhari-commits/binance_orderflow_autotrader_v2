from app.v9_costs import net_expectancy


def test_net_expectancy_subtracts_all_cost_components():
    costs = {"fee_bps": 1.0, "spread_bps": 0.8, "slippage_bps": 0.7, "funding_bps": 0.2}
    assert net_expectancy(5.0, costs) == 2.3


def test_missing_measured_cost_is_rejected():
    try:
        net_expectancy(5.0, {"fee_bps": 1.0, "spread_bps": 0.8})
    except ValueError:
        return
    assert False, "missing calibrated cost components must be rejected"
