"""Tests for BinanceMarketFeed synchronization / book-rebuild logic.

Validates the corrected synchronize() filter (drop events with
final_update_id <= snapshot lastUpdateId; keep the rest) and gap handling,
without a live network connection (snapshot is monkeypatched).
"""
from types import SimpleNamespace

from app.orderbook import LocalOrderBook
from app.models import DepthEvent, TradeEvent
from app.features import OrderFlowEngine
from app.binance_feed import BinanceMarketFeed


def _make_feed():
    cfg = SimpleNamespace(rest="https://example.invalid",
                          ws="wss://example.invalid")
    book = LocalOrderBook(20)
    flow = OrderFlowEngine(book)
    feed = BinanceMarketFeed(cfg, "btcusdt", book, flow, status_cb=lambda x: None)
    return feed, book


def test_synchronize_drops_stale_and_rebuilds():
    feed, book = _make_feed()
    snap = {"lastUpdateId": 100,
            "bids": [[100.0, 5.0], [99.0, 5.0]],
            "asks": [[101.0, 5.0], [102.0, 5.0]]}
    feed.snapshot = lambda: snap
    # stale (u=90, dropped), valid continuation (u=101, u=102)
    feed.buffer = [
        DepthEvent(1, 90, 90, [(100.0, 5.0)], [(101.0, 5.0)]),
        DepthEvent(2, 99, 101, [(100.0, 5.0)], [(101.0, 5.0)]),
        DepthEvent(3, 101, 102, [(100.0, 4.0)], [(101.0, 4.0)]),
    ]
    feed.ready = False
    ok = feed.synchronize()
    assert ok is True
    assert book.state.synchronized is True
    assert book.state.last_update_id == 102
    assert feed.buffer == []  # consumed
    assert book.state.bids[100.0] == 4.0  # last event reduced bid to 4.0


def test_synchronize_returns_false_on_gap():
    feed, book = _make_feed()
    feed.snapshot = lambda: {"lastUpdateId": 100,
                             "bids": [[100.0, 5.0]], "asks": [[101.0, 5.0]]}
    # first buffered event hole is far beyond the snapshot -> gap
    feed.buffer = [DepthEvent(2, 500, 600, [(100.0, 5.0)], [(101.0, 5.0)])]
    feed.ready = False
    ok = feed.synchronize()
    assert ok is False
    assert feed.ready is False
