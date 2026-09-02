from decimal import Decimal

import pandas as pd

from app.v10_empirical_fill import build_fill_observation, empirical_fill_summary


def test_build_fill_observation_preserves_partial_fill_and_adverse_selection():
    row = build_fill_observation(
        order_id="o1",
        signal_time_ns=1_000,
        order_time_ns=1_500,
        side="bid",
        quoted_price=Decimal("100"),
        quantity=Decimal("3"),
        queue_ahead=Decimal("2"),
        filled=Decimal("1"),
        first_fill_time_ns=2_000,
        mid_at_order=Decimal("100.0"),
        mid_after_fill=Decimal("99.95"),
        forward_mid=Decimal("99.90"),
    )
    assert row["order_id"] == "o1"
    assert row["fill_fraction"] == 1 / 3
    assert row["time_to_first_fill_ns"] == 500
    assert row["adverse_selection_bps"] > 0


def test_empirical_summary_reports_fill_rate_and_partial_rate():
    observations = pd.DataFrame(
        [
            {"fill_fraction": 1.0, "filled": 1, "adverse_selection_bps": 1.0, "net_ev_bps": 2.0},
            {"fill_fraction": 0.0, "filled": 0, "adverse_selection_bps": 0.0, "net_ev_bps": -0.1},
            {"fill_fraction": 0.5, "filled": 1, "adverse_selection_bps": 2.0, "net_ev_bps": -1.0},
        ]
    )
    result = empirical_fill_summary(observations)
    assert result["orders"] == 3
    assert result["filled_orders"] == 2
    assert result["fill_rate"] == 2 / 3
    assert result["partial_fill_rate_among_filled"] == 0.5
    assert result["mean_adverse_selection_bps"] == 1.5
    assert result["mean_net_ev_bps"] == 0.3
