import pytest

from app.research.v21_orderflow_core import (
    AlphaEstimate,
    BookTop,
    CausalOrderFlowState,
    LogisticOrderFlowAlpha,
    PassiveQuotePlanner,
)


def test_queue_imbalance_and_microprice_sign():
    top = BookTop(100.0, 90.0, 100.1, 10.0)
    assert CausalOrderFlowState.queue_imbalance(top) > 0
    assert CausalOrderFlowState.microprice_edge_bps(top) > 0


def test_ofi_top_of_book_formula():
    previous = BookTop(100.0, 10.0, 100.1, 10.0)
    current = BookTop(100.0, 15.0, 100.1, 8.0)
    assert CausalOrderFlowState.ofi_event(previous, current) == pytest.approx(7.0)


def test_ofi_1000ms_feature_is_exposed():
    state = CausalOrderFlowState()
    state.update_book(1_000, BookTop(100.0, 10.0, 100.1, 10.0))
    state.update_book(1_500, BookTop(100.0, 14.0, 100.1, 8.0))
    f = state.snapshot(1_500)
    assert hasattr(f, "ofi_1000ms")
    assert f.ofi_1000ms == f.ofi_500ms


def test_trade_imbalance_is_causal():
    state = CausalOrderFlowState()
    state.update_book(1_000, BookTop(100.0, 10.0, 100.1, 10.0))
    state.update_trade(1_000, 5.0, 500.0)
    state.update_book(1_100, BookTop(100.0, 12.0, 100.1, 5.0))
    f = state.snapshot(1_100)
    assert f.trade_imbalance_100ms == pytest.approx(1.0)


def test_snapshot_refuses_future_timestamp():
    state = CausalOrderFlowState()
    state.update_book(1_000, BookTop(100.0, 10.0, 100.1, 10.0))
    with pytest.raises(ValueError):
        state.snapshot(900)


def test_planner_suppresses_crossing_quotes_instead_of_clamping():
    planner = PassiveQuotePlanner(
        tick_size=0.1,
        maker_fee_bps=1.0,
        min_edge_bps=-100.0,
        inventory_penalty_bps=0.0,
        adverse_selection_buffer_bps=0.0,
    )
    # Large alpha shift makes the raw bid cross the real best bid.
    top = BookTop(100.0, 10.0, 100.1, 10.0)
    alpha = AlphaEstimate(p_up=0.9, p_down=0.1, expected_move_bps=20.0)
    decision = planner.decide(
        top=top,
        alpha=alpha,
        inventory_notional_usd=0.0,
        max_position_notional_usd=5_000.0,
        half_spread_bps=1.0,
    )
    assert decision.bid_crossing_request
    assert decision.bid_price is None
    assert decision.ask_price is not None


def test_inventory_shift_is_stabilizing():
    planner = PassiveQuotePlanner(
        tick_size=0.1,
        maker_fee_bps=0.0,
        min_edge_bps=-100.0,
        inventory_penalty_bps=10.0,
        adverse_selection_buffer_bps=0.0,
    )
    top = BookTop(100.0, 10.0, 100.1, 10.0)
    alpha = AlphaEstimate(p_up=0.5, p_down=0.5, expected_move_bps=0.0)

    long_decision = planner.decide(
        top=top,
        alpha=alpha,
        inventory_notional_usd=4_000.0,
        max_position_notional_usd=5_000.0,
        half_spread_bps=10.0,
    )
    short_decision = planner.decide(
        top=top,
        alpha=alpha,
        inventory_notional_usd=-4_000.0,
        max_position_notional_usd=5_000.0,
        half_spread_bps=2.0,
    )
    assert long_decision.ask_price is not None
    assert short_decision.ask_price is not None
    assert long_decision.ask_price < short_decision.ask_price


def test_alpha_inference_is_deterministic():
    model = LogisticOrderFlowAlpha((1.0, 0.1, 0.0, 0.0, 0.0, 0.0))
    features = CausalOrderFlowState
    top = BookTop(100.0, 20.0, 100.1, 1.0)
    state = CausalOrderFlowState()
    state.update_book(1_000, top)
    f = state.snapshot(1_000)
    e1 = model.estimate(f)
    e2 = model.estimate(f)
    assert e1 == e2
    assert e1.p_up > 0.5
