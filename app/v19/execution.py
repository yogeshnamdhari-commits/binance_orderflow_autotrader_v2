from __future__ import annotations

import math


def expected_net_pnl(
    predicted_return_bps: float,
    fill_probability: float,
    maker_round_trip_cost_bps: float,
    taker_round_trip_cost_bps: float,
    non_fill_opportunity_cost_bps: float,
    maker_share: float = 1.0,
    queue_position_cost_bps: float = 0.0,
) -> float:
    if not 0.0 <= fill_probability <= 1.0:
        raise ValueError("fill_probability must be in [0, 1]")
    if not 0.0 <= maker_share <= 1.0:
        raise ValueError("maker_share must be in [0, 1]")

    values = [
        predicted_return_bps, maker_round_trip_cost_bps,
        taker_round_trip_cost_bps, non_fill_opportunity_cost_bps,
        queue_position_cost_bps
    ]
    if not all(math.isfinite(float(x)) for x in values):
        raise ValueError("execution inputs must be finite")

    execution_cost = (
        maker_share * maker_round_trip_cost_bps +
        (1.0 - maker_share) * taker_round_trip_cost_bps +
        queue_position_cost_bps
    )

    return (
        fill_probability * (predicted_return_bps - execution_cost) -
        (1.0 - fill_probability) * non_fill_opportunity_cost_bps
    )


def simulate_realized_fill(
    predicted_return_bps: float,
    filled: bool,
    maker: bool,
    maker_cost_bps: float,
    taker_cost_bps: float,
    partial_fill_ratio: float = 1.0,
) -> float:
    if not math.isfinite(predicted_return_bps):
        raise ValueError("predicted_return_bps must be finite")
    if not 0.0 <= partial_fill_ratio <= 1.0:
        raise ValueError("partial_fill_ratio must be in [0, 1]")

    if not filled or partial_fill_ratio == 0.0:
        return 0.0

    cost = maker_cost_bps if maker else taker_cost_bps
    if cost < 0 or not math.isfinite(cost):
        raise ValueError("execution cost must be finite and non-negative")

    net = (predicted_return_bps - cost) * partial_fill_ratio
    return float(net)


def estimate_queue_position_cost(
    order_size_bps_of_spread: float,
    spread_bps: float,
    bid_qty: float,
    ask_qty: float,
) -> float:
    if order_size_bps_of_spread <= 0:
        return 0.0

    liquidity = (bid_qty + ask_qty) / 2.0
    if liquidity <= 0:
        return 0.0

    queue_cost = min(
        spread_bps * 0.5,
        (order_size_bps_of_spread / max(liquidity, 0.01)) * spread_bps
    )
    return float(max(0.0, queue_cost))
