from app.mm.execution_replay import (
    CancelEvent,
    PassiveQuoteReplay,
    QuoteIntent,
    ReplaceEvent,
    Side,
    TradeEvent,
    replay_trades,
)


def test_passive_bid_fills_only_after_queue_is_consumed():
    replay = PassiveQuoteReplay()
    replay.activate(
        QuoteIntent("q1", 1000, 100.0, 1.0, 101.0, 1.0),
        visible_bid_qty_at_price=0.5,
        visible_ask_qty_at_price=0.0,
    )

    assert replay.on_trade(TradeEvent(1100, 100.0, 0.25, Side.SELL, 1)) == []
    fills = replay.on_trade(TradeEvent(1200, 100.0, 0.75, Side.SELL, 2))

    assert len(fills) == 1
    assert fills[0].side is Side.BUY
    assert fills[0].price == 100.0
    assert fills[0].qty == 0.5


def test_passive_ask_fills_on_aggressive_buy():
    replay = PassiveQuoteReplay()
    replay.activate(
        QuoteIntent("q1", 1000, 99.0, 1.0, 101.0, 1.0),
        visible_bid_qty_at_price=0.0,
        visible_ask_qty_at_price=0.0,
    )

    fills = replay.on_trade(TradeEvent(1100, 101.0, 0.4, Side.BUY, 1))
    assert len(fills) == 1
    assert fills[0].side is Side.SELL
    assert fills[0].qty == 0.4


def test_trade_inside_quote_does_not_fill():
    replay = PassiveQuoteReplay()
    replay.activate(
        QuoteIntent("q1", 1000, 100.0, 1.0, 101.0, 1.0),
        visible_bid_qty_at_price=0.0,
        visible_ask_qty_at_price=0.0,
    )
    assert replay.on_trade(TradeEvent(1100, 100.5, 1.0, Side.BUY, 1)) == []
    assert replay.stats().fills == 0


def test_replay_is_deterministic_and_ordered():
    replay = PassiveQuoteReplay()
    replay.activate(
        QuoteIntent("q1", 1000, 100.0, 1.0, 101.0, 1.0),
        visible_bid_qty_at_price=0.0,
        visible_ask_qty_at_price=0.0,
    )
    events = [
        TradeEvent(1200, 100.0, 0.4, Side.SELL, 2),
        TradeEvent(1100, 100.0, 0.3, Side.SELL, 1),
    ]
    fills = replay_trades(replay, events)
    assert [f.trade_seq for f in fills] == [1, 2]
    assert sum(f.qty for f in fills) == 0.7


def test_replace_resets_queue_state_and_quote():
    replay = PassiveQuoteReplay()
    replay.activate(
        QuoteIntent("q1", 1000, 100.0, 1.0, 101.0, 1.0),
        visible_bid_qty_at_price=2.0,
        visible_ask_qty_at_price=0.0,
    )
    replay.replace(
        ReplaceEvent(2000, "q2", 99.0, 1.0, 101.5, 1.0, 2),
        visible_bid_qty_at_price=0.0,
        visible_ask_qty_at_price=0.0,
    )
    fills = replay.on_trade(TradeEvent(2100, 99.0, 0.5, Side.SELL, 3))
    assert len(fills) == 1
    assert fills[0].quote_id == "q2"


def test_full_fill_cancels_remaining_quote():
    replay = PassiveQuoteReplay()
    replay.activate(
        QuoteIntent("q1", 1000, 100.0, 0.5, 101.0, 0.5),
        visible_bid_qty_at_price=0.0,
        visible_ask_qty_at_price=0.0,
    )
    replay.on_trade(TradeEvent(1100, 100.0, 1.0, Side.SELL, 1))
    assert replay.on_trade(TradeEvent(1200, 100.0, 1.0, Side.SELL, 2)) == []
    assert replay.stats().fills == 1
