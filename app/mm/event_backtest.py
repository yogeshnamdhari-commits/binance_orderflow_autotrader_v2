from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Sequence
import math

from .book import L2Snapshot, L2Update, OrderBook
from .config import V20Config
from .execution_replay import PassiveQuoteReplay, QuoteIntent, Side, TradeEvent
from .backtest import generate_quotes


@dataclass(frozen=True)
class EventBacktestResult:
    """Execution-realism result; deliberately separate from V20-ECO-V1."""

    fills: int
    cancels: int
    replacements: int
    filled_qty: float
    fees_usd: float
    realized_pnl_usd: float
    inventory_mtm_usd: float
    net_pnl_usd: float
    avg_adverse_selection_bps: float
    as_by_horizon: dict[int, float] = field(default_factory=dict)
    final_inventory: float = 0.0
    toxicity_suppressed_quotes: int = 0
    toxic_flow_imbalance_mean: float = 0.0


def _future_mid_by_time(
    mids: Sequence[tuple[int, float]],
    fill_timestamp_ns: int,
    horizon_ns: int,
) -> float | None:
    candidates = [
        mid
        for ts, mid in mids
        if ts > fill_timestamp_ns and ts <= fill_timestamp_ns + horizon_ns and mid > 0
    ]
    return sum(candidates) / len(candidates) if candidates else None


def _adverse_selection(fill_price: float, side: Side, future_mid: float | None) -> float:
    if fill_price <= 0 or future_mid is None or future_mid <= 0:
        return 0.0
    if side is Side.BUY:
        return max(0.0, (fill_price - future_mid) / fill_price * 10_000.0)
    return max(0.0, (future_mid - fill_price) / fill_price * 10_000.0)


def _same_price_qty(book: OrderBook, side: str, price: float) -> float:
    levels = book.get_depth(side, levels=20)
    return sum(
        qty
        for level_price, qty in levels
        if math.isclose(
            level_price,
            price,
            rel_tol=0.0,
            abs_tol=max(price * 1e-9, 1e-8),
        )
    )


def _book_imbalance(book: OrderBook) -> float:
    bids = book.get_depth("bid", levels=1)
    asks = book.get_depth("ask", levels=1)
    if not bids or not asks:
        return 0.0
    bid_qty = max(0.0, bids[0][1])
    ask_qty = max(0.0, asks[0][1])
    denom = bid_qty + ask_qty
    return (bid_qty - ask_qty) / denom if denom > 0 else 0.0


def _quote_center(mid_price: float, imbalance: float, config: V20Config) -> float:
    """Shift the reservation/fair center with top-of-book imbalance."""
    skew = max(0.0, config.microprice_skew_bps) * max(-1.0, min(1.0, imbalance))
    return mid_price * (1.0 + skew / 10_000.0)


def run_event_backtest(
    snapshot: L2Snapshot,
    depth_events: Sequence[L2Update],
    trade_events: Sequence[TradeEvent],
    config: V20Config,
    *,
    horizon_ms: Sequence[int] = (1, 5, 10, 25, 50, 100),
) -> EventBacktestResult:
    """Replay depth and trade events chronologically with optional toxicity controls.

    Quotes are created only after the corresponding depth event. Aggressive trades
    that occurred earlier can therefore never fill a quote that did not yet exist.
    Candidate toxicity controls use only information available before each quote.
    """

    book = OrderBook.from_snapshot(snapshot)
    replay = PassiveQuoteReplay()
    sorted_depth = sorted(depth_events, key=lambda x: (x.timestamp_ns, x.final_update_id))
    sorted_trades = sorted(trade_events, key=lambda x: (x.timestamp_ns, x.event_seq))
    events: list[tuple[int, int, object]] = []
    # Depth is processed before trade when timestamps tie.
    events.extend((e.timestamp_ns, 0, e) for e in sorted_depth)
    events.extend((e.timestamp_ns, 1, e) for e in sorted_trades)
    events.sort(key=lambda x: (x[0], x[1]))

    flow_queue: deque[tuple[int, float]] = deque()
    signed_flow = 0.0
    total_flow = 0.0
    window_ns = max(1, int(config.flow_window_ms)) * 1_000_000

    mids: list[tuple[int, float]] = []
    inventory = 0.0
    cash = 0.0
    fees_usd = 0.0
    fills_for_as: list[tuple[int, Side, float]] = []

    last_quote: QuoteIntent | None = None
    quote_counter = 0
    replacements = 0
    toxicity_suppressed = 0
    toxic_flow_values: list[float] = []

    def process_trade(trade: TradeEvent) -> None:
        nonlocal inventory, cash, fees_usd
        for fill in replay.on_trade(trade):
            notional = fill.price * fill.qty
            fee = notional * config.maker_fee_bps / 10_000.0
            fees_usd += fee
            if fill.side is Side.BUY:
                inventory += fill.qty
                cash -= notional
            else:
                inventory -= fill.qty
                cash += notional
            cash -= fee
            fills_for_as.append((fill.timestamp_ns, fill.side, fill.price))

    for timestamp_ns, kind, event in events:
        if kind == 1:
            trade = event
            assert isinstance(trade, TradeEvent)
            qty = max(0.0, trade.qty)
            signed = qty if trade.aggressor_side is Side.BUY else -qty
            flow_queue.append((trade.timestamp_ns, signed))
            signed_flow += signed
            total_flow += qty
            cutoff = timestamp_ns - window_ns
            while flow_queue and flow_queue[0][0] < cutoff:
                _, old_signed = flow_queue.popleft()
                signed_flow -= old_signed
                total_flow -= abs(old_signed)
            process_trade(trade)
            continue

        depth_event = event
        assert isinstance(depth_event, L2Update)
        book.apply_update(depth_event)
        mid = book.get_mid_price()
        spread_bps = book.get_spread_bps()
        if mid <= 0 or spread_bps <= 0:
            continue

        mids.append((depth_event.timestamp_ns, mid))
        flow_imbalance = signed_flow / total_flow if total_flow > 0 else 0.0
        flow_imbalance = max(-1.0, min(1.0, flow_imbalance))
        book_imbalance = _book_imbalance(book)
        center = _quote_center(mid, book_imbalance, config)
        bid, ask, bid_qty, ask_qty = generate_quotes(center, spread_bps, inventory, config)

        if config.toxicity_filter_enabled:
            bull_toxic = (
                book_imbalance >= config.toxicity_imbalance_threshold
                and flow_imbalance >= config.toxicity_flow_threshold
            )
            bear_toxic = (
                book_imbalance <= -config.toxicity_imbalance_threshold
                and flow_imbalance <= -config.toxicity_flow_threshold
            )
            if bull_toxic:
                ask_qty = 0.0
                toxicity_suppressed += 1
                toxic_flow_values.append(abs(flow_imbalance))
            elif bear_toxic:
                bid_qty = 0.0
                toxicity_suppressed += 1
                toxic_flow_values.append(abs(flow_imbalance))

        desired = QuoteIntent(
            quote_id=f"v2q-{quote_counter}",
            timestamp_ns=depth_event.timestamp_ns,
            bid_price=bid,
            bid_qty=bid_qty,
            ask_price=ask,
            ask_qty=ask_qty,
        )

        def materially_different(a: QuoteIntent | None, b: QuoteIntent) -> bool:
            if a is None:
                return True
            price_eps = max(mid * 1e-10, 1e-8)
            return (
                abs(a.bid_price - b.bid_price) > price_eps
                or abs(a.ask_price - b.ask_price) > price_eps
                or (a.bid_qty <= 0) != (b.bid_qty <= 0)
                or (a.ask_qty <= 0) != (b.ask_qty <= 0)
                or replay.active_quote is None
            )

        if materially_different(last_quote, desired):
            quote_counter += 1
            desired = QuoteIntent(
                quote_id=f"v2q-{quote_counter}",
                timestamp_ns=depth_event.timestamp_ns,
                bid_price=desired.bid_price,
                bid_qty=desired.bid_qty,
                ask_price=desired.ask_price,
                ask_qty=desired.ask_qty,
            )
            bid_queue = _same_price_qty(book, "bid", desired.bid_price) if desired.bid_qty > 0 else 0.0
            ask_queue = _same_price_qty(book, "ask", desired.ask_price) if desired.ask_qty > 0 else 0.0
            if last_quote is not None:
                replacements += 1
            replay.activate(
                desired,
                visible_bid_qty_at_price=bid_queue,
                visible_ask_qty_at_price=ask_queue,
            )
            last_quote = desired

    stats = replay.stats()
    final_mid = mids[-1][1] if mids else 0.0
    inventory_mtm_usd = inventory * final_mid
    realized_pnl_usd = cash
    net_pnl_usd = realized_pnl_usd + inventory_mtm_usd

    as_by_horizon: dict[int, float] = {}
    for horizon in horizon_ms:
        values: list[float] = []
        horizon_ns = int(horizon * 1_000_000)
        for ts, side, price in fills_for_as:
            future_mid = _future_mid_by_time(mids, ts, horizon_ns)
            values.append(_adverse_selection(price, side, future_mid))
        as_by_horizon[horizon] = sum(values) / len(values) if values else 0.0

    avg_as = sum(as_by_horizon.values()) / len(as_by_horizon) if as_by_horizon else 0.0
    return EventBacktestResult(
        fills=stats.fills,
        cancels=stats.cancels_seen,
        replacements=replacements,
        filled_qty=stats.filled_qty,
        fees_usd=fees_usd,
        realized_pnl_usd=realized_pnl_usd,
        inventory_mtm_usd=inventory_mtm_usd,
        net_pnl_usd=net_pnl_usd,
        avg_adverse_selection_bps=avg_as,
        as_by_horizon=as_by_horizon,
        final_inventory=inventory,
        toxicity_suppressed_quotes=toxicity_suppressed,
        toxic_flow_imbalance_mean=(sum(toxic_flow_values) / len(toxic_flow_values) if toxic_flow_values else 0.0),
    )
