from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
import numpy as np
import math


@dataclass(frozen=True)
class FillResult:
    filled: bool
    fill_price: float
    fill_qty: float
    adverse_selection_bps: float
    reason: str


def estimate_queue_position(
    quote_qty: float,
    available_depth: list[tuple[float, float]],
    side: str,
) -> int:
    """
    Estimate your position in the order queue.
    Returns position 0 (front), 1 (second), etc.
    """
    if not available_depth:
        return 0

    cumulative_qty = 0.0
    for position, (price, qty) in enumerate(available_depth):
        cumulative_qty += qty
        if cumulative_qty >= quote_qty:
            return position

    return len(available_depth) - 1


def compute_fill_probability(
    queue_position: int,
    total_depth_qty: float,
    quote_qty: float,
    volatility_regime: int,
) -> float:
    """
    Probability of fill based on queue position.

    Front of queue (position 0): ~95% fill
    Position 1–2: ~70% fill
    Position 3+: ~30% fill

    In high-vol regime, fills are less likely.
    In low-vol regime, fills are more likely.
    """
    base_prob = {
        0: 0.95,
        1: 0.70,
        2: 0.50,
        3: 0.30,
    }

    prob = base_prob.get(queue_position, 0.15)

    if volatility_regime == 2:
        prob *= 0.7
    elif volatility_regime == 0:
        prob *= 1.1

    if total_depth_qty > 0:
        size_ratio = quote_qty / total_depth_qty
        if size_ratio > 0.1:
            prob *= max(0.0, 1.0 - size_ratio * 0.5)

    return max(0.0, min(1.0, prob))


def simulate_fill(
    quote_price: float,
    quote_qty: float,
    side: str,
    available_depth: list[tuple[float, float]],
    mid_price_at_fill_time: float,
    volatility_regime: int,
    latency_ms: float = 100.0,
) -> FillResult:
    """
    Simulate a realistic fill with probabilistic execution.
    """

    queue_position = estimate_queue_position(quote_qty, available_depth, side)
    total_depth_qty = sum(q for _, q in available_depth)
    fill_prob = compute_fill_probability(
        queue_position,
        total_depth_qty,
        quote_qty,
        volatility_regime,
    )

    latency_decay = 1.0 - (latency_ms / 1000.0) * 0.1
    fill_prob *= latency_decay

    if np.random.random() > fill_prob:
        return FillResult(
            filled=False,
            fill_price=0.0,
            fill_qty=0.0,
            adverse_selection_bps=0.0,
            reason=f"no_fill (prob={fill_prob:.2%}, queue_pos={queue_position})",
        )

    price_slippage_bps = queue_position * 0.5

    if side == "BUY":
        fill_price = quote_price + (price_slippage_bps / 10_000.0) * quote_price
    else:
        fill_price = quote_price - (price_slippage_bps / 10_000.0) * quote_price

    partial_fill_ratio = np.random.uniform(0.5, 1.0)
    fill_qty = quote_qty * partial_fill_ratio

    if side == "BUY":
        adverse_selection_bps = max(
            0.0,
            (mid_price_at_fill_time - fill_price) * 10_000.0 / fill_price,
        )
    else:
        adverse_selection_bps = max(
            0.0,
            (fill_price - mid_price_at_fill_time) * 10_000.0 / fill_price,
        )

    return FillResult(
        filled=True,
        fill_price=fill_price,
        fill_qty=fill_qty,
        adverse_selection_bps=adverse_selection_bps,
        reason=f"filled (prob={fill_prob:.2%}, queue_pos={queue_position}, partial={partial_fill_ratio:.2%})",
    )


def compute_realized_pnl(
    fill_price: float,
    fill_qty: float,
    quote_price: float,
    side: str,
    maker_fee_bps: float,
    taker_fee_bps: float,
    is_maker: bool,
    adverse_selection_bps: float,
) -> float:
    """
    Compute realized PnL per fill in bps.
    """

    if not fill_qty or fill_price <= 0:
        return 0.0

    if side == "BUY":
        spread_capture_bps = (quote_price - fill_price) * 10_000.0 / fill_price
    else:
        spread_capture_bps = (fill_price - quote_price) * 10_000.0 / quote_price

    fee_bps = maker_fee_bps if is_maker else taker_fee_bps
    realized_pnl_bps = spread_capture_bps - fee_bps - adverse_selection_bps

    return realized_pnl_bps
