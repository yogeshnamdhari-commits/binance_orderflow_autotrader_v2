from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
import numpy as np

from app.v19.features import L2Event


@dataclass(frozen=True)
class FillResult:
    side: str
    filled: bool
    price: float
    qty: float
    realized_pnl_bps: float
    queue_position: int
    adverse_selection_bps: float


class FillSimulator:
    def __init__(
        self,
        maker_fee_bps: float = 0.0,
        taker_fee_bps: float = 3.0,
    ):
        self.maker_fee_bps = maker_fee_bps
        self.taker_fee_bps = taker_fee_bps

    def simulate_fill(
        self,
        quote_side: str,
        quote_price: float,
        quote_qty: float,
        best_bid: float,
        best_ask: float,
        trade_price: float,
        trade_qty: float,
        trade_side: str,
        queue_depth: int,
    ) -> FillResult:
        if quote_side == "BUY" and trade_side == "SELL" and trade_price <= quote_price:
            filled = True
            queue_position = self._estimate_queue_position(
                quote_price, best_bid, queue_depth, trade_qty
            )
            adverse_selection = self._compute_adverse_selection(
                quote_price, trade_price, queue_position
            )
            realized_pnl = self._compute_realized_pnl(
                quote_side, quote_price, trade_price, adverse_selection
            )
            return FillResult(
                side=quote_side,
                filled=True,
                price=quote_price,
                qty=min(quote_qty, trade_qty),
                realized_pnl_bps=float(realized_pnl),
                queue_position=queue_position,
                adverse_selection_bps=float(adverse_selection),
            )
        elif quote_side == "SELL" and trade_side == "BUY" and trade_price >= quote_price:
            filled = True
            queue_position = self._estimate_queue_position(
                quote_price, best_ask, queue_depth, trade_qty
            )
            adverse_selection = self._compute_adverse_selection(
                quote_price, trade_price, queue_position
            )
            realized_pnl = self._compute_realized_pnl(
                quote_side, quote_price, trade_price, adverse_selection
            )
            return FillResult(
                side=quote_side,
                filled=True,
                price=quote_price,
                qty=min(quote_qty, trade_qty),
                realized_pnl_bps=float(realized_pnl),
                queue_position=queue_position,
                adverse_selection_bps=float(adverse_selection),
            )
        else:
            return FillResult(
                side=quote_side,
                filled=False,
                price=quote_price,
                qty=0.0,
                realized_pnl_bps=0.0,
                queue_position=0,
                adverse_selection_bps=0.0,
            )

    def _estimate_queue_position(
        self,
        quote_price: float,
        best_price: float,
        queue_depth: int,
        trade_qty: float,
    ) -> int:
        if queue_depth <= 0:
            return 1
        price_priority = max(0, (quote_price - best_price) * 10_000 / best_price) if best_price > 0 else 0
        if price_priority <= 0:
            return queue_depth + 1
        return max(1, queue_depth // 2)

    def _compute_adverse_selection(
        self,
        quote_price: float,
        trade_price: float,
        queue_position: int,
    ) -> float:
        if queue_position <= 1:
            return 0.0
        price_diff = abs(trade_price - quote_price) * 10_000
        queue_penalty = queue_position * 0.1
        return float(price_diff + queue_penalty)

    def _compute_realized_pnl(
        self,
        quote_side: str,
        quote_price: float,
        trade_price: float,
        adverse_selection_bps: float,
    ) -> float:
        if quote_side == "BUY":
            spread_capture = (trade_price - quote_price) * 10_000
        else:
            spread_capture = (quote_price - trade_price) * 10_000
        fee_cost = self.maker_fee_bps
        net_pnl = spread_capture - fee_cost - adverse_selection_bps
        return float(net_pnl)

    def compute_queue_position_cost(
        self,
        quote_price: float,
        best_bid: float,
        best_ask: float,
        queue_depth: int,
    ) -> float:
        if queue_depth <= 0:
            return 0.0
        if quote_price <= best_bid or quote_price >= best_ask:
            return 0.0
        distance = min(
            (quote_price - best_bid) * 10_000 / best_bid if best_bid > 0 else 0,
            (best_ask - quote_price) * 10_000 / best_ask if best_ask > 0 else 0,
        )
        return float(min(distance * 0.5, 0.5))
