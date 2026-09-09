import pytest

from app.v19.execution import expected_net_pnl, simulate_realized_fill


def test_non_fill_cost_is_conditional():
    assert expected_net_pnl(4.0, 0.5, 1.0, 2.0, 0.8, 1.0) == pytest.approx(0.6)


def test_realized_non_fill_has_no_execution_cost():
    assert simulate_realized_fill(4.0, False, True, 1.0, 2.0) == pytest.approx(0.0)


def test_taker_share_changes_expected_cost():
    maker = expected_net_pnl(5.0, 1.0, 1.0, 3.0, 0.0, 1.0)
    taker = expected_net_pnl(5.0, 1.0, 1.0, 3.0, 0.0, 0.0)
    assert maker > taker
