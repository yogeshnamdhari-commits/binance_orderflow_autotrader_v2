"""Causal V21 order-flow research primitives.

Research-only module. No exchange connectivity and no order submission.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import exp, floor, ceil
from typing import Deque, Optional


@dataclass(frozen=True)
class BookTop:
    bid_price: float
    bid_qty: float
    ask_price: float
    ask_qty: float

    @property
    def valid(self) -> bool:
        return (
            self.bid_price > 0
            and self.ask_price > 0
            and self.bid_qty >= 0
            and self.ask_qty >= 0
            and self.bid_price < self.ask_price
        )

    @property
    def mid(self) -> float:
        return (self.bid_price + self.ask_price) / 2.0

    @property
    def spread_bps(self) -> float:
        if not self.valid or self.mid <= 0:
            return 0.0
        return (self.ask_price - self.bid_price) * 10_000.0 / self.mid


@dataclass(frozen=True)
class OrderFlowFeatures:
    timestamp_ms: int
    queue_imbalance: float
    microprice_edge_bps: float
    ofi_100ms: float
    ofi_500ms: float
    ofi_1000ms: float
    trade_imbalance_100ms: float
    trade_imbalance_500ms: float
    trade_imbalance_1000ms: float
    trade_intensity_notional_s: float
    spread_bps: float
    mid_return_100ms_bps: float
    mid_return_500ms_bps: float


@dataclass
class _BookHistory:
    timestamp_ms: int
    top: BookTop


class CausalOrderFlowState:
    """Incremental causal feature state.

    Book updates are expected in authoritative exchange sequence order.
    Trade updates may be supplied in timestamp order.
    Feature snapshots never inspect future events.
    """

    def __init__(self, *, max_history_ms: int = 2_000) -> None:
        self.max_history_ms = max_history_ms
        self._book_history: Deque[_BookHistory] = deque()
        self._ofi_events: Deque[tuple[int, float]] = deque()
        self._trades: Deque[tuple[int, float, float]] = deque()
        self._previous_top: Optional[BookTop] = None

    @staticmethod
    def ofi_event(previous: BookTop, current: BookTop) -> float:
        if not previous.valid or not current.valid:
            return 0.0

        if current.bid_price > previous.bid_price:
            bid_component = current.bid_qty
        elif current.bid_price < previous.bid_price:
            bid_component = -previous.bid_qty
        else:
            bid_component = current.bid_qty - previous.bid_qty

        if current.ask_price < previous.ask_price:
            ask_component = -current.ask_qty
        elif current.ask_price > previous.ask_price:
            ask_component = previous.ask_qty
        else:
            ask_component = -(current.ask_qty - previous.ask_qty)

        return bid_component + ask_component

    @staticmethod
    def queue_imbalance(top: BookTop) -> float:
        denom = top.bid_qty + top.ask_qty
        if denom <= 0:
            return 0.0
        return (top.bid_qty - top.ask_qty) / denom

    @staticmethod
    def microprice_edge_bps(top: BookTop) -> float:
        denom = top.bid_qty + top.ask_qty
        if denom <= 0 or not top.valid:
            return 0.0
        micro = (
            top.ask_price * top.bid_qty + top.bid_price * top.ask_qty
        ) / denom
        return (micro - top.mid) * 10_000.0 / top.mid

    def _trim(self, timestamp_ms: int) -> None:
        cutoff = timestamp_ms - self.max_history_ms
        while self._book_history and self._book_history[0].timestamp_ms < cutoff:
            self._book_history.popleft()
        while self._ofi_events and self._ofi_events[0][0] < cutoff:
            self._ofi_events.popleft()
        while self._trades and self._trades[0][0] < cutoff:
            self._trades.popleft()

    def update_book(self, timestamp_ms: int, top: BookTop) -> float:
        """Apply a causally ordered book state and return its OFI event."""
        if not top.valid:
            raise ValueError("invalid top-of-book state")
        ofi = 0.0 if self._previous_top is None else self.ofi_event(self._previous_top, top)
        self._previous_top = top
        self._book_history.append(_BookHistory(timestamp_ms, top))
        self._ofi_events.append((timestamp_ms, ofi))
        self._trim(timestamp_ms)
        return ofi

    def update_trade(
        self,
        timestamp_ms: int,
        signed_qty: float,
        notional_usd: float,
    ) -> None:
        if timestamp_ms < 0:
            raise ValueError("timestamp_ms must be non-negative")
        if notional_usd < 0:
            raise ValueError("notional_usd must be non-negative")
        self._trades.append((timestamp_ms, signed_qty, notional_usd))
        self._trim(timestamp_ms)

    def _sum_ofi(self, timestamp_ms: int, window_ms: int) -> float:
        cutoff = timestamp_ms - window_ms
        return sum(value for ts, value in self._ofi_events if cutoff <= ts <= timestamp_ms)

    def _trade_stats(self, timestamp_ms: int, window_ms: int) -> tuple[float, float]:
        cutoff = timestamp_ms - window_ms
        signed = 0.0
        absolute = 0.0
        for ts, sq, _ in self._trades:
            if cutoff <= ts <= timestamp_ms:
                signed += sq
                absolute += abs(sq)
        return signed, absolute

    def _trade_imbalance(self, timestamp_ms: int, window_ms: int) -> float:
        signed, absolute = self._trade_stats(timestamp_ms, window_ms)
        return signed / absolute if absolute > 0 else 0.0

    def _trade_intensity(self, timestamp_ms: int, window_ms: int = 1_000) -> float:
        cutoff = timestamp_ms - window_ms
        notional = sum(n for ts, _, n in self._trades if cutoff <= ts <= timestamp_ms)
        return notional * 1_000.0 / window_ms

    def _past_mid(self, timestamp_ms: int, window_ms: int) -> Optional[float]:
        target = timestamp_ms - window_ms
        candidate = None
        for item in self._book_history:
            if item.timestamp_ms > target:
                break
            candidate = item.top.mid
        return candidate

    def snapshot(self, timestamp_ms: int) -> OrderFlowFeatures:
        if not self._book_history:
            raise ValueError("book state is empty")
        current = self._book_history[-1].top
        if self._book_history[-1].timestamp_ms > timestamp_ms:
            raise ValueError("snapshot timestamp precedes latest book state")

        self._trim(timestamp_ms)
        past_100 = self._past_mid(timestamp_ms, 100)
        past_500 = self._past_mid(timestamp_ms, 500)
        current_mid = current.mid
        ret_100 = (
            (current_mid / past_100 - 1.0) * 10_000.0
            if past_100 and past_100 > 0
            else 0.0
        )
        ret_500 = (
            (current_mid / past_500 - 1.0) * 10_000.0
            if past_500 and past_500 > 0
            else 0.0
        )
        signed_500, absolute_500 = self._trade_stats(timestamp_ms, 500)
        return OrderFlowFeatures(
            timestamp_ms=timestamp_ms,
            queue_imbalance=self.queue_imbalance(current),
            microprice_edge_bps=self.microprice_edge_bps(current),
            ofi_100ms=self._sum_ofi(timestamp_ms, 100),
            ofi_500ms=self._sum_ofi(timestamp_ms, 500),
            ofi_1000ms=self._sum_ofi(timestamp_ms, 1_000),
            trade_imbalance_100ms=self._trade_imbalance(timestamp_ms, 100),
            trade_imbalance_500ms=signed_500 / absolute_500 if absolute_500 > 0 else 0.0,
            trade_imbalance_1000ms=self._trade_imbalance(timestamp_ms, 1_000),
            trade_intensity_notional_s=self._trade_intensity(timestamp_ms),
            spread_bps=current.spread_bps,
            mid_return_100ms_bps=ret_100,
            mid_return_500ms_bps=ret_500,
        )


@dataclass(frozen=True)
class AlphaEstimate:
    p_up: float
    p_down: float
    expected_move_bps: float


class LogisticOrderFlowAlpha:
    """Simple calibrated-style probabilistic alpha.

    Coefficients must be learned offline; this class performs only inference.
    """

    def __init__(self, coefficients: tuple[float, ...], intercept: float = 0.0) -> None:
        if len(coefficients) != 6:
            raise ValueError("expected 6 coefficients")
        self.coefficients = coefficients
        self.intercept = intercept

    def estimate(self, features: OrderFlowFeatures) -> AlphaEstimate:
        x = (
            features.queue_imbalance,
            features.microprice_edge_bps,
            features.ofi_500ms,
            features.trade_imbalance_500ms,
            features.spread_bps,
            features.mid_return_500ms_bps,
        )
        z = self.intercept + sum(a * b for a, b in zip(self.coefficients, x))
        p_up = 1.0 / (1.0 + exp(-max(-60.0, min(60.0, z))))
        p_down = 1.0 - p_up
        expected_move = (p_up - p_down) * max(0.0, features.spread_bps)
        return AlphaEstimate(p_up=p_up, p_down=p_down, expected_move_bps=expected_move)


@dataclass(frozen=True)
class QuoteDecision:
    bid_price: Optional[float]
    ask_price: Optional[float]
    bid_enabled: bool
    ask_enabled: bool
    bid_edge_bps: float
    ask_edge_bps: float
    bid_crossing_request: bool
    ask_crossing_request: bool


class PassiveQuotePlanner:
    """Inventory/alpha quote planner with a hard passive invariant."""

    def __init__(
        self,
        *,
        tick_size: float,
        maker_fee_bps: float,
        min_edge_bps: float,
        inventory_penalty_bps: float,
        adverse_selection_buffer_bps: float,
    ) -> None:
        if tick_size <= 0:
            raise ValueError("tick_size must be positive")
        self.tick_size = tick_size
        self.maker_fee_bps = maker_fee_bps
        self.min_edge_bps = min_edge_bps
        self.inventory_penalty_bps = inventory_penalty_bps
        self.adverse_selection_buffer_bps = adverse_selection_buffer_bps

    def _floor_tick(self, price: float) -> float:
        return floor(price / self.tick_size) * self.tick_size

    def _ceil_tick(self, price: float) -> float:
        return ceil(price / self.tick_size) * self.tick_size

    def decide(
        self,
        *,
        top: BookTop,
        alpha: AlphaEstimate,
        inventory_notional_usd: float,
        max_position_notional_usd: float,
        half_spread_bps: float,
    ) -> QuoteDecision:
        if not top.valid:
            raise ValueError("invalid top-of-book")
        if max_position_notional_usd <= 0:
            raise ValueError("max_position_notional_usd must be positive")

        inventory_fraction = max(
            -1.0,
            min(1.0, inventory_notional_usd / max_position_notional_usd),
        )
        inventory_shift_bps = -inventory_fraction * self.inventory_penalty_bps
        reservation_bps = alpha.expected_move_bps + inventory_shift_bps
        reservation = top.mid * (1.0 + reservation_bps / 10_000.0)

        raw_bid = reservation * (1.0 - half_spread_bps / 10_000.0)
        raw_ask = reservation * (1.0 + half_spread_bps / 10_000.0)

        # A maker quote may improve the current BBO by sitting inside the spread.
        # It is marketable only when it crosses the opposite side.
        bid_cross = raw_bid >= top.ask_price - 1e-12
        ask_cross = raw_ask <= top.bid_price + 1e-12

        bid = None if bid_cross else self._floor_tick(raw_bid)
        ask = None if ask_cross else self._ceil_tick(raw_ask)

        if bid is not None and bid >= top.ask_price:
            bid = None
            bid_cross = True
        if ask is not None and ask <= top.bid_price:
            ask = None
            ask_cross = True
        if bid is not None and ask is not None and bid >= ask:
            bid = None
            ask = None
            bid_cross = True
            ask_cross = True

        bid_capture = ((top.mid - bid) * 10_000.0 / bid) if bid and bid > 0 else 0.0
        ask_capture = ((ask - top.mid) * 10_000.0 / ask) if ask and ask > 0 else 0.0

        bid_edge = bid_capture + alpha.expected_move_bps - self.maker_fee_bps - self.adverse_selection_buffer_bps
        ask_edge = ask_capture - alpha.expected_move_bps - self.maker_fee_bps - self.adverse_selection_buffer_bps

        bid_enabled = bid is not None and bid_edge >= self.min_edge_bps
        ask_enabled = ask is not None and ask_edge >= self.min_edge_bps

        return QuoteDecision(
            bid_price=bid if bid_enabled else None,
            ask_price=ask if ask_enabled else None,
            bid_enabled=bid_enabled,
            ask_enabled=ask_enabled,
            bid_edge_bps=bid_edge,
            ask_edge_bps=ask_edge,
            bid_crossing_request=bid_cross,
            ask_crossing_request=ask_cross,
        )
