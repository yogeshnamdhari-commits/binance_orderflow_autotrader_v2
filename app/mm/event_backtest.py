from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence
import math

from .book import L2Snapshot, L2Update, OrderBook
from .config import V20Config
from .execution_replay import PassiveQuoteReplay, QuoteIntent, Side, TradeEvent
from .backtest import compute_volatility_regime, generate_quotes


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


def run_event_backtest(
    snapshot: L2Snapshot,
    depth_events: Sequence[L2Update],
    trade_events: Sequence[TradeEvent],
    config: V20Config,
    *,
    horizon_ms: Sequence[int] = (1, 5, 10, 25, 50, 100),
) -> EventBacktestResult:
    """Replay passive execution from observed trades instead of random fill draws.

    Strategy quote parameters are read directly from V20Config and are not changed
    here. The only changed variable versus V1 is the execution/fill mechanism.
    """

    book = OrderBook.from_snapshot(snapshot)
    replay = PassiveQuoteReplay()
    sorted_trades = sorted(trade_events, key=lambda x: (x.timestamp_ns, x.event_seq))
    trade_index = 0
    mids: list[tuple[int, float]] = []
    spread_history: list[float] = []
    inventory = 0.0
    cash = 0.0
    fees_usd = 0.0
    fills_for_as: list[tuple[int, Side, float]] = []

    last_quote: QuoteIntent | None = None
    quote_counter = 0
    replacements = 0

    def process_fills(trades: Sequence[TradeEvent]) -> None:
        nonlocal inventory, cash, fees_usd
        for trade in trades:
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

    for depth_event in depth_events:
        book.apply_update(depth_event)
        mid = book.get_mid_price()
        spread_bps = book.get_spread_bps()
        if mid <= 0 or spread_bps <= 0:
            continue

        mids.append((depth_event.timestamp_ns, mid))
        spread_history.append(spread_bps)
        bid, ask, bid_qty, ask_qty = generate_quotes(mid, spread_bps, inventory, config)

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
            price_eps = max(bid * 1e-10, 1e-8)
            return (
                abs(a.bid_price - b.bid_price) > price_eps
                or abs(a.ask_price - b.ask_price) > price_eps
                or a.bid_qty <= 0
                or a.ask_qty <= 0
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
            bid_queue = _same_price_qty(book, "bid", desired.bid_price)
            ask_queue = _same_price_qty(book, "ask", desired.ask_price)
            if last_quote is not None:
                replacements += 1
            replay.activate(
                desired,
                visible_bid_qty_at_price=bid_queue,
                visible_ask_qty_at_price=ask_queue,
            )
            last_quote = desired

        due: list[TradeEvent] = []
        while trade_index < len(sorted_trades) and sorted_trades[trade_index].timestamp_ns <= depth_event.timestamp_ns:
            due.append(sorted_trades[trade_index])
            trade_index += 1
        process_fills(due)

    process_fills(sorted_trades[trade_index:])

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
    )
