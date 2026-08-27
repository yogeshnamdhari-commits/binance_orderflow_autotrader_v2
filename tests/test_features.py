"""Tests for the production order-flow feature engine (app.features)."""
import math
import pytest
from app.orderbook import LocalOrderBook
from app.models import DepthEvent, TradeEvent
from app.features import OrderFlowEngine


def _seeded_book():
    b = LocalOrderBook(20)
    bids = [[100.0 - i, 1.0] for i in range(10)]
    asks = [[101.0 + i, 1.0] for i in range(10)]
    b.load_snapshot(bids, asks, 1000)
    b.state.synchronized = True
    b.state.last_event_ms = 1_000_000
    return b


def _trade(ts, price, qty, maker=False):
    return TradeEvent(ts, ts, price, qty, maker)


def test_snapshot_populates_core_and_extended_fields():
    book = _seeded_book()
    eng = OrderFlowEngine(book, window_ms=5000)
    now = 1_000_000
    for i in range(20):
        eng.on_trade(_trade(now - (20 - i) * 100, 100.5, 1.0, maker=(i % 2 == 0)))
    f = eng.snapshot(now_ms=now)
    assert f.mid == 100.5
    assert f.spread_bps == pytest.approx(10000 * (101.0 - 100.0) / 100.5)
    assert f.imbalance_1 == 0.0  # symmetric 1 lot each side at touch
    assert f.cvd == 0.0  # 10 buy + 10 sell
    assert f.book_state == "BOOK_VALID"
    # extended fields present and finite
    for name in ("microprice", "depth_weighted_pressure", "vpin",
                 "kyle_lambda", "cancel_pressure", "liquidity_depletion",
                 "replenishment", "sweep_intensity", "absorption_proxy"):
        val = getattr(f, name)
        assert isinstance(val, float) and not math.isnan(val), name


def test_aggression_delta_sign():
    book = _seeded_book()
    eng = OrderFlowEngine(book, window_ms=5000)
    now = 1_000_000
    for i in range(10):
        eng.on_trade(_trade(now - (10 - i) * 100, 100.5, 1.0, maker=False))  # all BUY
    f = eng.snapshot(now_ms=now)
    assert f.delta == 10.0
    assert f.trade_imbalance == 1.0
    assert f.aggressive_buy_ratio == 1.0


def test_book_event_ofi_and_cancellation():
    book = _seeded_book()
    eng = OrderFlowEngine(book, window_ms=5000)
    # First call establishes prev_depth as the baseline (full size).
    eng.on_book_event(DepthEvent(1_000_000, 1001, 1001,
                                 [(100.0, 1.0)], [(101.0, 1.0)]))
    # Halving the bid size is a cancellation => negative OFI contribution.
    x = eng.on_book_event(DepthEvent(1_000_001, 1002, 1002,
                                     [(100.0, 0.5)], [(101.0, 1.0)]))
    assert x < 0  # size removed on bid side => negative OFI contribution
    assert eng.ofi == x


def test_snapshot_events_event_time_aggregation():
    book = _seeded_book()
    eng = OrderFlowEngine(book, window_ms=5000)
    now = 1_000_000
    for i in range(30):
        eng.on_trade(_trade(now - (30 - i) * 50, 100.5, 1.0, maker=(i % 3 == 0)))
    f = eng.snapshot_events(n=10, now_ms=now)
    assert f.n_trades == 10
    assert f.book_state == "BOOK_VALID"
