import numpy as np
import pytest
from app.v10_adverse_selection import conditional_mid_return, adverse_selection_bps


def test_conditional_mid_return_uses_post_fill_mid():
    result = conditional_mid_return(np.array([100.0, 100.1]), np.array([100.0, 100.2]))
    assert np.allclose(result, [0.0, 0.000999001])


def test_adverse_selection_is_positive_for_move_against_passive_bid():
    # Passive bid filled at 100; mid subsequently falls 10 bps.
    assert adverse_selection_bps(fill_price=100.0, post_fill_mid=99.9, side="bid") == pytest.approx(10.0)


def test_passive_bid_with_rising_mid_is_favorable():
    assert adverse_selection_bps(fill_price=100.0, post_fill_mid=100.1, side="bid") == pytest.approx(-10.0)


def test_invalid_side_rejected():
    try:
        adverse_selection_bps(100, 100, "middle")
    except ValueError:
        return
    assert False
