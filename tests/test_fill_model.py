import json
from app.fillmodel import PassiveFillModel
from app.integrity_gate import IntegrityGate
from app.orderbook import LocalOrderBook


def _cal():
    return {"results": {
        "delta_5s_dec10_long@15s": {
            "n": 1000, "p_fill_same_tick": 0.7, "p_fill_1_tick_inside": 0.5,
            "e_fill_return_bps": 1.5, "gross_unconditional_bps": 2.0,
            "mean_time_to_fill_ms": 5000.0},
        "delta_5s_dec1_short@15s": {
            "n": 1000, "p_fill_same_tick": 0.65, "p_fill_1_tick_inside": 0.45,
            "e_fill_return_bps": 1.4, "gross_unconditional_bps": 1.9,
            "mean_time_to_fill_ms": 4000.0}}}


def test_fill_model_net_edge_positive_when_fill_cheap():
    m = PassiveFillModel(_cal(), maker_fee_rt_bps=0.5, min_fill_prob=0.2)
    d = m.evaluate("delta_5s_dec10_long", 15_000, 10_000)
    assert d.allowed
    assert d.net_edge_bps > 0


def test_fill_model_blocks_when_fee_dominates():
    m = PassiveFillModel(_cal(), maker_fee_rt_bps=6.0, min_fill_prob=0.2)
    d = m.evaluate("delta_5s_dec10_long", 15_000, 10_000)
    assert not d.allowed
    assert d.net_edge_bps < 0


def test_fill_model_blocks_low_fill_prob():
    m = PassiveFillModel(_cal(), maker_fee_rt_bps=0.5, min_fill_prob=0.9)
    d = m.evaluate("delta_5s_dec10_long", 15_000, 10_000)
    assert not d.allowed
    assert d.reason == "fill probability too low"


def test_fill_model_depth_factor_caps_probability():
    m = PassiveFillModel(_cal(), maker_fee_rt_bps=0.5, min_fill_prob=0.2)
    b = LocalOrderBook(10)
    b.load_snapshot([(100.0, 0.001)], [(100.1, 0.001)], 1)  # ~$0.1 depth
    d = m.evaluate("delta_5s_dec10_long", 15_000, 10_000, book=b)
    assert d.p_fill == 0.0  # depth factor ~0 -> no fill


def test_gate_chain_requires_all():
    g = IntegrityGate()
    assert not g.evaluate()["SIGNAL_ALLOWED"]
    g.on_book_sync(True)
    assert not g.evaluate()["SIGNAL_ALLOWED"]
    g.on_features(True)
    assert not g.evaluate()["SIGNAL_ALLOWED"]
    g.on_cost(True)
    assert g.evaluate()["SIGNAL_ALLOWED"]
    g.on_book_sync(False)
    assert not g.evaluate()["SIGNAL_ALLOWED"]


def test_next_le_and_ge_semantics():
    import numpy as np
    from app.hist.fill_calib import next_le, next_ge
    p = np.array([100.0, 99.9, 100.1, 99.8])
    nle = next_le(p)
    assert list(nle) == [1, 3, 3, -1]
    nge = next_ge(p)
    assert list(nge) == [2, 2, -1, -1]