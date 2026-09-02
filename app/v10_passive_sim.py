"""Deterministic research-only passive-order fill simulation primitives.

This module models a hypothetical order at one price level. It does not
claim to reconstruct exchange FIFO queue position exactly; queue-ahead must
come from an explicitly supplied estimate. Trade volume is credited only when
an aggressive trade is consistent with the passive side and occurs at the
quoted price. Partial fills are preserved.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PassiveOrder:
    side: str
    price: Decimal
    quantity: Decimal
    queue_ahead: Decimal
    filled: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.side not in {"bid", "ask"}:
            raise ValueError("side must be bid or ask")
        if self.price <= 0 or self.quantity <= 0 or self.queue_ahead < 0 or self.filled < 0:
            raise ValueError("invalid passive order state")
        if self.filled > self.quantity:
            raise ValueError("filled cannot exceed quantity")

    @property
    def remaining(self) -> Decimal:
        return self.quantity - self.filled


def apply_trade(order: PassiveOrder, trade_price: Decimal, trade_quantity: Decimal, buyer_is_maker: bool) -> PassiveOrder:
    """Apply one trade to the hypothetical order conservatively.

    Binance aggTrade's ``m`` flag means the buyer is the maker. Therefore a
    bid is exposed to seller-initiated flow when m=True, while an ask is
    exposed to buyer-initiated flow when m=False. Trades at other prices do
    not consume the order. Queue-ahead is consumed before our quantity.
    """
    price = Decimal(str(trade_price))
    qty = Decimal(str(trade_quantity))
    if price <= 0 or qty < 0:
        raise ValueError("invalid trade")
    if qty == 0 or price != order.price or order.remaining == 0:
        return order

    aggressive_against_us = buyer_is_maker if order.side == "bid" else not buyer_is_maker
    if not aggressive_against_us:
        return order

    consumed_ahead = min(order.queue_ahead, qty)
    remaining_trade = qty - consumed_ahead
    new_ahead = order.queue_ahead - consumed_ahead
    additional_fill = min(order.remaining, remaining_trade)
    return PassiveOrder(
        side=order.side,
        price=order.price,
        quantity=order.quantity,
        queue_ahead=new_ahead,
        filled=order.filled + additional_fill,
    )
