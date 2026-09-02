from decimal import Decimal
import pytest
from app.v10_passive_sim import PassiveOrder, apply_trade


def test_bid_consumes_queue_then_partially_fills():
    order = PassiveOrder("bid", Decimal("100"), Decimal("3"), Decimal("2"))
    order = apply_trade(order, Decimal("100"), Decimal("3"), buyer_is_maker=True)
    assert order.queue_ahead == Decimal("0")
    assert order.filled == Decimal("1")


def test_ask_requires_aggressive_buy_trade():
    order = PassiveOrder("ask", Decimal("100"), Decimal("2"), Decimal("0"))
    unchanged = apply_trade(order, Decimal("100"), Decimal("2"), buyer_is_maker=True)
    assert unchanged.filled == Decimal("0")
    filled = apply_trade(order, Decimal("100"), Decimal("2"), buyer_is_maker=False)
    assert filled.filled == Decimal("2")


def test_other_price_does_not_fill():
    order = PassiveOrder("bid", Decimal("100"), Decimal("2"), Decimal("0"))
    result = apply_trade(order, Decimal("100.1"), Decimal("10"), buyer_is_maker=True)
    assert result == order


def test_invalid_order_rejected():
    with pytest.raises(ValueError):
        PassiveOrder("bid", Decimal("0"), Decimal("1"), Decimal("0"))
