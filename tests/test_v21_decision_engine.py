from app.research.v21_decision_engine import ToxicityEstimate, V21DecisionEngine
from app.research.v21_orderflow_core import AlphaEstimate, BookTop


def _engine():
    return V21DecisionEngine(
        tick_size=0.1,
        maker_fee_bps=1.0,
        min_edge_bps=0.05,
        inventory_penalty_bps=5.0,
    )


def test_crossing_request_is_suppressed_not_clamped():
    engine = _engine()
    decision = engine.decide(
        top=BookTop(100.0, 10.0, 100.1, 10.0),
        alpha=AlphaEstimate(0.9, 0.1, 20.0),
        buy_toxicity=ToxicityEstimate(0.1, 0.1),
        sell_toxicity=ToxicityEstimate(0.1, 0.1),
        inventory_notional_usd=0.0,
        max_position_notional_usd=5_000.0,
        half_spread_bps=1.0,
    )
    assert decision.bid_crossing_request
    assert decision.bid_price is None


def test_high_toxicity_can_disable_one_side():
    engine = _engine()
    decision = engine.decide(
        top=BookTop(100.0, 10.0, 100.1, 10.0),
        alpha=AlphaEstimate(0.5, 0.5, 0.0),
        buy_toxicity=ToxicityEstimate(1.0, 20.0),
        sell_toxicity=ToxicityEstimate(0.0, 0.0),
        inventory_notional_usd=0.0,
        max_position_notional_usd=5_000.0,
        half_spread_bps=6.0,
    )
    assert not decision.bid_enabled
    assert decision.ask_enabled


def test_long_inventory_shifts_reservation_down():
    engine = _engine()
    long_decision = engine.decide(
        top=BookTop(100.0, 10.0, 100.1, 10.0),
        alpha=AlphaEstimate(0.5, 0.5, 0.0),
        buy_toxicity=ToxicityEstimate(0.0, 0.0),
        sell_toxicity=ToxicityEstimate(0.0, 0.0),
        inventory_notional_usd=4_000.0,
        max_position_notional_usd=5_000.0,
        half_spread_bps=2.0,
    )
    flat_decision = engine.decide(
        top=BookTop(100.0, 10.0, 100.1, 10.0),
        alpha=AlphaEstimate(0.5, 0.5, 0.0),
        buy_toxicity=ToxicityEstimate(0.0, 0.0),
        sell_toxicity=ToxicityEstimate(0.0, 0.0),
        inventory_notional_usd=0.0,
        max_position_notional_usd=5_000.0,
        half_spread_bps=2.0,
    )
    assert long_decision.reservation_shift_bps < flat_decision.reservation_shift_bps
