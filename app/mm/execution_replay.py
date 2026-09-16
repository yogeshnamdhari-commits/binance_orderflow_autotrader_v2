from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Sequence


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class QuoteIntent:
    """A passive quote that is active until cancelled, replaced, or filled."""

    quote_id: str
    timestamp_ns: int
    bid_price: float
    bid_qty: float
    ask_price: float
    ask_qty: float


@dataclass(frozen=True)
class TradeEvent:
    """Normalized aggressive trade from the captured market stream.

    aggressor_side is the taker's direction: BUY consumes asks; SELL consumes bids.
    """

    timestamp_ns: int
    price: float
    qty: float
    aggressor_side: Side
    event_seq: int = 0


@dataclass(frozen=True)
class CancelEvent:
    timestamp_ns: int
    quote_id: str
    event_seq: int = 0


@dataclass(frozen=True)
class ReplaceEvent:
    timestamp_ns: int
    quote_id: str
    bid_price: float
    bid_qty: float
    ask_price: float
    ask_qty: float
    event_seq: int = 0


@dataclass(frozen=True)
class ReplayFill:
    timestamp_ns: int
    quote_id: str
    side: Side
    price: float
    qty: float
    trade_timestamp_ns: int
    trade_seq: int


@dataclass(frozen=True)
class ReplayStats:
    quotes_seen: int
    cancels_seen: int
    replacements_seen: int
    trades_seen: int
    fills: int
    filled_qty: float
    orphan_trades: int = 0


class PassiveQuoteReplay:
    """Event-driven passive-fill model using observed trades.

    This model deliberately does not generate random fills. A passive BUY can only
    fill when an observed aggressive SELL trades at or below the bid. A passive
    SELL can only fill when an observed aggressive BUY trades at or above the ask.

    Queue position is represented conservatively by visible same-price quantity at
    quote activation. Trade volume at the same price consumes that queue before our
    order can receive a fill. This is still an approximation, but it is auditable
    and deterministic and can be strengthened when per-order queue data exists.
    """

    def __init__(self) -> None:
        self._quote: QuoteIntent | None = None
        self._bid_queue_ahead = 0.0
        self._ask_queue_ahead = 0.0
        self._fills: list[ReplayFill] = []
        self._quotes_seen = 0
        self._cancels_seen = 0
        self._replacements_seen = 0
        self._trades_seen = 0
        self._orphan_trades = 0

    def activate(
        self,
        quote: QuoteIntent,
        *,
        visible_bid_qty_at_price: float,
        visible_ask_qty_at_price: float,
    ) -> None:
        self.cancel()
        self._quote = quote
        self._quotes_seen += 1
        self._bid_queue_ahead = max(0.0, visible_bid_qty_at_price)
        self._ask_queue_ahead = max(0.0, visible_ask_qty_at_price)

    def cancel(self) -> None:
        if self._quote is not None:
            self._cancels_seen += 1
        self._quote = None
        self._bid_queue_ahead = 0.0
        self._ask_queue_ahead = 0.0

    def replace(
        self,
        event: ReplaceEvent,
        *,
        visible_bid_qty_at_price: float,
        visible_ask_qty_at_price: float,
    ) -> None:
        self._replacements_seen += 1
        self.activate(
            QuoteIntent(
                quote_id=event.quote_id,
                timestamp_ns=event.timestamp_ns,
                bid_price=event.bid_price,
                bid_qty=event.bid_qty,
                ask_price=event.ask_price,
                ask_qty=event.ask_qty,
            ),
            visible_bid_qty_at_price=visible_bid_qty_at_price,
            visible_ask_qty_at_price=visible_ask_qty_at_price,
        )

    def on_trade(self, trade: TradeEvent) -> list[ReplayFill]:
        self._trades_seen += 1
        quote = self._quote
        if quote is None or trade.qty <= 0 or trade.price <= 0:
            self._orphan_trades += 1
            return []

        if trade.aggressor_side is Side.SELL and trade.price <= quote.bid_price:
            remaining_trade = trade.qty
            if trade.price == quote.bid_price and self._bid_queue_ahead > 0:
                consumed = min(self._bid_queue_ahead, remaining_trade)
                self._bid_queue_ahead -= consumed
                remaining_trade -= consumed
            fill_qty = min(max(0.0, remaining_trade), quote.bid_qty)
            if fill_qty > 0:
                fill = ReplayFill(
                    timestamp_ns=trade.timestamp_ns,
                    quote_id=quote.quote_id,
                    side=Side.BUY,
                    price=quote.bid_price,
                    qty=fill_qty,
                    trade_timestamp_ns=trade.timestamp_ns,
                    trade_seq=trade.event_seq,
                )
                self._fills.append(fill)
                self._quote = QuoteIntent(
                    quote.quote_id,
                    quote.timestamp_ns,
                    quote.bid_price,
                    max(0.0, quote.bid_qty - fill_qty),
                    quote.ask_price,
                    quote.ask_qty,
                )
                if self._quote.bid_qty == 0:
                    self.cancel()
                return [fill]
            return []

        if trade.aggressor_side is Side.BUY and trade.price >= quote.ask_price:
            remaining_trade = trade.qty
            if trade.price == quote.ask_price and self._ask_queue_ahead > 0:
                consumed = min(self._ask_queue_ahead, remaining_trade)
                self._ask_queue_ahead -= consumed
                remaining_trade -= consumed
            fill_qty = min(max(0.0, remaining_trade), quote.ask_qty)
            if fill_qty > 0:
                fill = ReplayFill(
                    timestamp_ns=trade.timestamp_ns,
                    quote_id=quote.quote_id,
                    side=Side.SELL,
                    price=quote.ask_price,
                    qty=fill_qty,
                    trade_timestamp_ns=trade.timestamp_ns,
                    trade_seq=trade.event_seq,
                )
                self._fills.append(fill)
                self._quote = QuoteIntent(
                    quote.quote_id,
                    quote.timestamp_ns,
                    quote.bid_price,
                    quote.bid_qty,
                    quote.ask_price,
                    max(0.0, quote.ask_qty - fill_qty),
                )
                if self._quote.ask_qty == 0:
                    self.cancel()
                return [fill]
            return []

        self._orphan_trades += 1
        return []

    def fills(self) -> tuple[ReplayFill, ...]:
        return tuple(self._fills)

    def stats(self) -> ReplayStats:
        return ReplayStats(
            quotes_seen=self._quotes_seen,
            cancels_seen=self._cancels_seen,
            replacements_seen=self._replacements_seen,
            trades_seen=self._trades_seen,
            fills=len(self._fills),
            filled_qty=sum(f.qty for f in self._fills),
            orphan_trades=self._orphan_trades,
        )


def replay_trades(replay: PassiveQuoteReplay, events: Sequence[TradeEvent]) -> tuple[ReplayFill, ...]:
    """Replay normalized trades in deterministic event order."""
    ordered = sorted(events, key=lambda e: (e.timestamp_ns, e.event_seq))
    for event in ordered:
        replay.on_trade(event)
    return replay.fills()
