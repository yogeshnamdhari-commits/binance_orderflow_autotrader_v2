import pytest

from app.mm.config import V20Config
from scripts.v20_performance_certify import _candidate_grid, _select_candidate


def test_candidate_grid_covers_tighter_passive_spreads_with_fixed_budget():
    base = V20Config(
        base_half_spread_bps=2.0,
        max_half_spread_bps=3.0,
        quote_size_usd=100.0,
        maker_fee_bps=1.0,
        taker_fee_bps=3.0,
    )
    candidates = _candidate_grid(base)
    spreads = {c.base_half_spread_bps for c in candidates}
    skews = {c.microprice_skew_bps for c in candidates}

    # The research budget remains fixed at 6 spreads x 3 imbalance
    # thresholds x 2 flow thresholds x 3 microprice skews.
    assert len(candidates) == 108
    assert spreads == {0.50, 0.75, 1.00, 1.25, 1.50, 2.00}
    assert skews == {0.25, 0.50, 1.00}


def test_candidate_selection_rejects_sparse_training_candidates():
    candidates = [
        {"fills": 2, "objective": 0.50, "net_pnl_usd": 0.50, "name": "sparse"},
        {"fills": 20, "objective": 0.20, "net_pnl_usd": 0.20, "name": "viable"},
        {"fills": 35, "objective": 0.10, "net_pnl_usd": 0.10, "name": "more_viable"},
    ]

    selected = _select_candidate(candidates, min_train_fills=10)

    assert selected["name"] == "viable"


def test_candidate_selection_fails_when_no_training_candidate_is_viable():
    candidates = [
        {"fills": 1, "objective": 0.50, "net_pnl_usd": 0.50, "name": "sparse"},
        {"fills": 5, "objective": 0.20, "net_pnl_usd": 0.20, "name": "still_sparse"},
    ]

    with pytest.raises(ValueError, match="no candidate meets minimum training fills"):
        _select_candidate(candidates, min_train_fills=10)
