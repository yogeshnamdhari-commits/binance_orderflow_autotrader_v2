from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Sequence
import math

from .book import L2Snapshot, L2Update, OrderBook
from .config import V20Config
from .execution_replay import PassiveQuoteReplay, QuoteIntent, Side, TradeEvent
from .backtest import generate_quotes, _enforce_passive_geometry


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
    gross_spread_capture_usd: float = 0.0
    adverse_selection_usd: float = 0.0
    execution_effects_usd: float = 0.0
    buy_fills: int = 0
    sell_fills: int = 0
    buy_filled_qty: float = 0.0
    sell_filled_qty: float = 0.0
    quote_crossings_detected: int = 0
    quote_crossings_suppressed: int = 0
    inventory_trajectory: tuple[tuple[int, float], ...] = field(default_factory=tuple)
    avg_fill_holding_time_ns: float = 0.0
    inventory_max: float = 0.0
    inventory_limit_breaches: int = 0
    inventory_carry_usd: float = 0.0
    attribution_residual_usd: float = 0.0
    inventory_suppression_events: int = 0
    inventory_suppressed_bid_qty: float = 0.0
    inventory_suppressed_ask_qty: float = 0.0
    inventory_ratio_abs_mean: float = 0.0
    inventory_ratio_abs_max: float = 0.0


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
    book_side = book.bids if side == "bid" else book.asks
    return book_side.get(price, 0.0)


def _book_imbalance(book: OrderBook) -> float:
    if not book.bids or not book.asks:
        return 0.0
    best_bid = max(book.bids.keys())
    best_ask = min(book.asks.keys())
    bid_qty = max(0.0, book.bids[best_bid])
    ask_qty = max(0.0, book.asks[best_ask])
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
    quote_interval_ns = max(1, config.quote_interval_ms) * 1_000_000
    last_quote_time_ns: int | None = None
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
    fill_records: list[dict[str, float | int | Side]] = []

    quote_crossings_detected = 0
    quote_crossings_suppressed = 0
    gross_spread_capture_usd = 0.0
    adverse_selection_usd = 0.0
    execution_effects_usd = 0.0
    buy_fills = 0
    sell_fills = 0
    buy_filled_qty = 0.0
    sell_filled_qty = 0.0
    inventory_trajectory: list[tuple[int, float]] = []
    fill_holding_times: list[float] = []
    buy_queue: deque[tuple[int, float]] = deque()
    inventory_max = 0.0

    last_quote: QuoteIntent | None = None
    quote_counter = 0
    replacements = 0
    toxicity_suppressed = 0
    toxic_flow_values: list[float] = []
    current_mid = 0.0
    inventory_max = 0.0
    inventory_limit_breaches = 0
    mid_price_movement_usd = 0.0
    inventory_suppression_events = 0
    inventory_suppressed_bid_qty = 0.0
    inventory_suppressed_ask_qty = 0.0
    inventory_ratio_abs_samples: list[float] = []

    def process_trade(trade: TradeEvent) -> None:
        nonlocal inventory, cash, fees_usd, buy_fills, sell_fills
        nonlocal buy_filled_qty, sell_filled_qty, gross_spread_capture_usd
        nonlocal fill_records, inventory_trajectory, current_mid, inventory_max
        nonlocal mid_price_movement_usd, inventory_limit_breaches
        for fill in replay.on_trade(trade):
            notional = fill.price * fill.qty
            fill_price_mid = current_mid

            if fill.side is Side.BUY:
                prospective_inventory = inventory + fill.qty
            else:
                prospective_inventory = inventory - fill.qty

            if fill_price_mid > 0:
                prospective_exposure = abs(prospective_inventory) * fill_price_mid
                if prospective_exposure > config.max_position_notional_usd + 1e-6:
                    inventory_limit_breaches += 1
                    continue

            fee = notional * (config.maker_fee_bps - config.maker_rebate_bps) / 10_000.0
            fees_usd += fee
            if fill.side is Side.BUY:
                inventory += fill.qty
                cash -= notional
                buy_fills += 1
                buy_filled_qty += fill.qty
                buy_queue.append((fill.timestamp_ns, fill.qty))
                if current_mid > 0:
                    gross_spread_capture_usd += (current_mid - fill.price) * fill.qty
            else:
                inventory -= fill.qty
                cash += notional
                sell_fills += 1
                sell_filled_qty += fill.qty
                remaining_sell = fill.qty
                while remaining_sell > 0 and buy_queue:
                    buy_ts, buy_qty = buy_queue[0]
                    matched = min(buy_qty, remaining_sell)
                    fill_holding_times.append(float(fill.timestamp_ns - buy_ts))
                    remaining_sell -= matched
                    if matched < buy_qty:
                        buy_queue[0] = (buy_ts, buy_qty - matched)
                    else:
                        buy_queue.popleft()
                if current_mid > 0:
                    gross_spread_capture_usd += (fill.price - current_mid) * fill.qty
            cash -= fee
            if fill.side is Side.BUY:
                mid_price_movement_usd -= fill_price_mid * fill.qty
            else:
                mid_price_movement_usd += fill_price_mid * fill.qty
            fills_for_as.append((fill.timestamp_ns, fill.side, fill.price))
            fill_records.append({
                "timestamp_ns": fill.timestamp_ns,
                "side": fill.side,
                "price": fill.price,
                "qty": fill.qty,
                "notional": notional,
                "mid": current_mid,
            })
            inventory_trajectory.append((fill.timestamp_ns, inventory))
            if current_mid > 0:
                inventory_max = max(inventory_max, abs(inventory * current_mid))

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
        if not book.bids or not book.asks:
            continue
        mid_keys_bid = max(book.bids.keys()) if book.bids else 0.0
        mid_keys_ask = min(book.asks.keys()) if book.asks else float("inf")
        if mid_keys_bid >= mid_keys_ask or mid_keys_bid <= 0 or mid_keys_ask <= 0:
            continue
        mid = (mid_keys_bid + mid_keys_ask) / 2.0
        spread_bps = (mid_keys_ask - mid_keys_bid) * 10_000.0 / mid
        current_mid = mid
        if last_quote_time_ns is not None and timestamp_ns - last_quote_time_ns < quote_interval_ns:
            continue
        last_quote_time_ns = timestamp_ns

        mids.append((depth_event.timestamp_ns, mid))
        flow_imbalance = signed_flow / total_flow if total_flow > 0 else 0.0
        flow_imbalance = max(-1.0, min(1.0, flow_imbalance))
        book_imbalance = _book_imbalance(book)
        center = _quote_center(mid, book_imbalance, config)
        bid, ask, bid_qty, ask_qty = generate_quotes(center, spread_bps, inventory, config)

        # Isolated inventory-suppression experiment.  The frozen V20 baseline
        # leaves quote sizes unchanged.  The candidate continuously reduces
        # only the side that would increase the existing inventory.  The scale
        # is deterministic, bounded in [0, 1], and uses only state available
        # before the quote is activated.
        inventory_ratio = 0.0
        if config.inventory_suppression_enabled and mid > 0:
            inventory_drift = inventory - config.inventory_target
            inventory_ratio = max(-1.0, min(1.0, inventory_drift * mid / max(config.max_position_notional_usd, 1e-9)))
            inventory_ratio_abs_samples.append(abs(inventory_ratio))
            suppression_power = max(config.inventory_suppression_power, 1e-9)
            suppression_strength = min(1.0, abs(inventory_ratio) ** suppression_power)
            side_scale = max(0.0, 1.0 - suppression_strength)
            if inventory_ratio > 0.0:
                previous = bid_qty
                bid_qty *= side_scale
                inventory_suppressed_bid_qty += max(0.0, previous - bid_qty)
                if previous > 0 and bid_qty < previous:
                    inventory_suppression_events += 1
            elif inventory_ratio < 0.0:
                previous = ask_qty
                ask_qty *= side_scale
                inventory_suppressed_ask_qty += max(0.0, previous - ask_qty)
                if previous > 0 and ask_qty < previous:
                    inventory_suppression_events += 1

        # Enforce inventory risk limit: suppress the side that would increase
        # exposure beyond max_position_notional_usd.  This is a hard stop —
        # the strategy must not accumulate inventory beyond the configured cap.
        current_exposure = abs(inventory) * mid
        if current_exposure >= config.max_position_notional_usd and mid > 0:
            if inventory > 0:
                bid_qty = 0.0
                inventory_limit_breaches += 1
            elif inventory < 0:
                ask_qty = 0.0
                inventory_limit_breaches += 1

        best_bid = max(book.bids.keys()) if book.bids else 0.0
        best_ask = min(book.asks.keys()) if book.asks else float("inf")
        crossed = False
        if best_bid < best_ask:
            if bid > best_bid or ask < best_ask:
                crossed = True
                quote_crossings_detected += 1
                if bid > best_bid and bid_qty > 0:
                    bid_qty = 0.0
                    quote_crossings_suppressed += 1
                if ask < best_ask and ask_qty > 0:
                    ask_qty = 0.0
                    quote_crossings_suppressed += 1
            bid = min(bid, best_bid)
            ask = max(ask, best_ask)
            # Push quotes to the top of book when outside the market spread.
            # A passive MM must quote at or inside best bid/ask to receive
            # fills from observed trade events.
            bid = max(bid, best_bid)
            ask = min(ask, best_ask)

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
            qty_eps = max(config.quote_size_usd / max(mid, 1e-9) * 0.001, 1e-12)
            qty_changed = (
                config.inventory_suppression_enabled
                and (
                    abs(a.bid_qty - b.bid_qty) > qty_eps
                    or abs(a.ask_qty - b.ask_qty) > qty_eps
                )
            )
            return (
                abs(a.bid_price - b.bid_price) > price_eps
                or abs(a.ask_price - b.ask_price) > price_eps
                or (a.bid_qty <= 0) != (b.bid_qty <= 0)
                or (a.ask_qty <= 0) != (b.ask_qty <= 0)
                or qty_changed
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
            last_quote_time_ns = timestamp_ns

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
    total_fill_notional = sum(r["notional"] for r in fill_records)
    adverse_selection_usd = total_fill_notional * avg_as / 10_000.0
    avg_holding_time_ns = (
        sum(fill_holding_times) / len(fill_holding_times) if fill_holding_times else 0.0
    )
    attribution_sum = gross_spread_capture_usd + mid_price_movement_usd - fees_usd
    attribution_residual_usd = realized_pnl_usd - attribution_sum
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
        gross_spread_capture_usd=gross_spread_capture_usd,
        adverse_selection_usd=adverse_selection_usd,
        execution_effects_usd=execution_effects_usd,
        buy_fills=buy_fills,
        sell_fills=sell_fills,
        buy_filled_qty=buy_filled_qty,
        sell_filled_qty=sell_filled_qty,
        quote_crossings_detected=quote_crossings_detected,
        quote_crossings_suppressed=quote_crossings_suppressed,
        inventory_trajectory=tuple(inventory_trajectory),
        avg_fill_holding_time_ns=avg_holding_time_ns,
        inventory_max=inventory_max,
        inventory_limit_breaches=inventory_limit_breaches,
        inventory_carry_usd=mid_price_movement_usd,
        attribution_residual_usd=round(attribution_residual_usd, 8),
        inventory_suppression_events=inventory_suppression_events,
        inventory_suppressed_bid_qty=inventory_suppressed_bid_qty,
        inventory_suppressed_ask_qty=inventory_suppressed_ask_qty,
        inventory_ratio_abs_mean=(sum(inventory_ratio_abs_samples) / len(inventory_ratio_abs_samples) if inventory_ratio_abs_samples else 0.0),
        inventory_ratio_abs_max=(max(inventory_ratio_abs_samples) if inventory_ratio_abs_samples else 0.0),
    )
