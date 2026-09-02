import pytest

from app.v10_execution_economics import (
    FillObservation,
    PassiveQuote,
    adverse_selection_bps,
    passive_order_ev_bps,
)
from app.v10_survival import kaplan_meier_fill_probability
from app.v10_walkforward import chronological_folds


def test_kaplan_meier_counts_censored_orders_correctly():
    observations = [(1.0, True), (2.0, False), (3.0, True)]
    result = kaplan_meier_fill_probability(observations, horizon=2.5)
    assert result.n == 3
    assert result.events == 1
    assert result.probability == pytest.approx(1.0 / 3.0)


def test_adverse_selection_is_signed_by_passive_side():
    assert adverse_selection_bps("BUY", 100.0, 100.10) == pytest.approx(-10.0)
    assert adverse_selection_bps("BUY", 100.0, 99.90) == pytest.approx(10.0)
    assert adverse_selection_bps("SELL", 100.0, 100.10) == pytest.approx(10.0)


def test_passive_order_ev_includes_fill_probability_and_costs():
    quote = PassiveQuote(side="BUY", price=99.95, mid=100.0, maker_fee_bps=1.0)
    ev = passive_order_ev_bps(quote, fill_probability=0.5, adverse_selection_cost_bps=2.0)
    assert ev == pytest.approx(1.0)


def test_walk_forward_folds_are_strictly_chronological_and_non_overlapping():
    folds = chronological_folds(list(range(10)), train_size=4, test_size=2, step=2)
    assert [(f.train, f.test) for f in folds] == [
        ((0, 1, 2, 3), (4, 5)),
        ((2, 3, 4, 5), (6, 7)),
        ((4, 5, 6, 7), (8, 9)),
    ]


def test_fill_observation_requires_positive_horizon():
    with pytest.raises(ValueError):
        FillObservation(fill_time_ms=0.0, filled=True)
