"""Frozen ACTIVE_FLOW_HEDGE-0.1 quote mechanics for live execution.

This module is a production adapter, not a new strategy. The calculations mirror
the existing retrospective implementation and use only state available at quote time.
"""

from __future__ import annotations

from dataclasses import dataclass

from .backtest import generate_quotes
from .book import OrderBook
from .config import V20Config


@dataclass(frozen=True)
class LiveQuotePair:
    bid_price: float
    bid_qty: float
    ask_price: float
    ask_qty: float


class ActiveFlowHedgeQuoteEngine:
    def __init__(self, config: V20Config) -> None:
        self.config = config

    @staticmethod
    def _book_imbalance(book: OrderBook) -> float:
        if not book.bids or not book.asks:
            return 0.0
        bid = max(book.bids)
        ask = min(book.asks)
        bq = max(0.0, book.bids[bid])
        aq = max(0.0, book.asks[ask])
        den = bq + aq
        return (bq - aq) / den if den > 0 else 0.0

    def build(
        self,
        *,
        book: OrderBook,
        inventory: float,
        flow_imbalance: float,
        inventory_limit_breaches: int = 0,
        inventory_penalty_bps: float | None = None,
        quote_size_scale: float = 1.0,
    ) -> LiveQuotePair:
        if not book.is_valid():
            raise ValueError("invalid order book")

        mid = book.get_mid_price()
        spread_bps = book.get_spread_bps()
        imbalance = max(-1.0, min(1.0, self._book_imbalance(book)))
        center = mid * (
            1.0
            + max(0.0, self.config.microprice_skew_bps) * imbalance / 10_000.0
        )
        flow = max(-1.0, min(1.0, flow_imbalance))

        if inventory_penalty_bps is None:
            if (
                self.config.inventory_penalty_slope > 0
                and self.config.max_position_notional_usd > 0
            ):
                inventory_pct = abs(inventory * mid) / self.config.max_position_notional_usd
                penalty_steps = int(inventory_pct * 10)
                inventory_penalty_bps = (
                    self.config.inventory_penalty_base_bps
                    + self.config.inventory_penalty_slope * penalty_steps
                )
            else:
                inventory_penalty_bps = self.config.inventory_penalty_bps

        if inventory_limit_breaches > 0 and self.config.quote_size_reduction_after_breach > 0:
            quote_size_scale = max(
                0.0, 1.0 - self.config.quote_size_reduction_after_breach
            )

        bid, ask, bid_qty, ask_qty = generate_quotes(
            center,
            spread_bps,
            inventory,
            self.config,
            inventory_penalty_bps=inventory_penalty_bps,
            flow_imbalance=flow,
            flow_quote_bias_bps=self.config.flow_quote_bias_bps,
            quote_size_scale=quote_size_scale,
        )

        # Existing candidate: passive inventory quote augmentation.
        current_exposure = abs(inventory) * mid
        if self.config.hedge_threshold_notional > 0 and self.config.hedge_ratio > 0:
            excess = max(0.0, current_exposure - self.config.hedge_threshold_notional)
            if excess > 0:
                hedge_qty = self.config.hedge_ratio * (excess / mid)
                if inventory > 0:
                    ask_qty = max(ask_qty, hedge_qty * 0.1)
                elif inventory < 0:
                    bid_qty = max(bid_qty, hedge_qty * 0.1)

        # Existing candidate: toxicity and directional-flow suppression.
        bull_toxic = (
            self.config.toxicity_filter_enabled
            and imbalance >= self.config.toxicity_imbalance_threshold
            and flow >= self.config.toxicity_flow_threshold
        )
        bear_toxic = (
            self.config.toxicity_filter_enabled
            and imbalance <= -self.config.toxicity_imbalance_threshold
            and flow <= -self.config.toxicity_flow_threshold
        )
        if bull_toxic:
            ask_qty = 0.0
        elif bear_toxic:
            bid_qty = 0.0

        if self.config.directional_flow_enabled:
            if flow >= self.config.directional_flow_threshold:
                bid_qty = 0.0
                if self.config.directional_flow_weight > 0:
                    scale = max(
                        0.0,
                        1.0 - min(1.0, abs(flow) * self.config.directional_flow_weight),
                    )
                    ask_qty *= scale
                if self.config.directional_flow_spread_bps > 0:
                    ask *= (
                        1.0
                        + abs(flow)
                        * self.config.directional_flow_spread_bps
                        / 10_000.0
                    )
            elif flow <= -self.config.directional_flow_threshold:
                ask_qty = 0.0
                if self.config.directional_flow_weight > 0:
                    scale = max(
                        0.0,
                        1.0 - min(1.0, abs(flow) * self.config.directional_flow_weight),
                    )
                    bid_qty *= scale
                if self.config.directional_flow_spread_bps > 0:
                    bid *= (
                        1.0
                        - abs(flow)
                        * self.config.directional_flow_spread_bps
                        / 10_000.0
                    )

        # Existing inventory suppression.
        if self.config.inventory_suppression_enabled and self.config.max_position_notional_usd > 0:
            ratio = min(
                1.0,
                abs(inventory * mid) / self.config.max_position_notional_usd,
            )
            power = max(0.0, self.config.inventory_suppression_power)
            scale = max(0.0, 1.0 - ratio ** power)
            if inventory > 0:
                bid_qty *= scale
            elif inventory < 0:
                ask_qty *= scale

        return LiveQuotePair(
            bid_price=bid,
            bid_qty=max(0.0, bid_qty),
            ask_price=ask,
            ask_qty=max(0.0, ask_qty),
        )
