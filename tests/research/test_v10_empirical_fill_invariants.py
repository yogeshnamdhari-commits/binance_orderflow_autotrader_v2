import pandas as pd
import pytest

from app.v10_empirical_fill import empirical_fill_summary


def test_empty_observations_rejected():
    with pytest.raises(ValueError, match="non-empty"):
        empirical_fill_summary(pd.DataFrame(columns=[
            "fill_fraction", "filled", "adverse_selection_bps", "net_ev_bps"
        ]))


def test_invalid_fill_fraction_rejected():
    observations = pd.DataFrame([
        {"fill_fraction": 1.1, "filled": 1, "adverse_selection_bps": 0.0, "net_ev_bps": 0.0}
    ])
    with pytest.raises(ValueError, match="fill_fraction"):
        empirical_fill_summary(observations)
