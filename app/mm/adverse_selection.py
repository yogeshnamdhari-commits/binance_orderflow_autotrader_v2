from __future__ import annotations

import numpy as np


def compute_post_fill_adverse_selection(
    fill_price: float,
    fill_time_idx: int,
    mid_prices: list[float],
    lookback_window: int = 50,
) -> float:
    """
    Measure adverse selection as mid-price drift AFTER fill.
    """

    if fill_time_idx + lookback_window >= len(mid_prices):
        lookback_window = len(mid_prices) - fill_time_idx - 1

    if lookback_window <= 0:
        return 0.0

    mid_post_fill = mid_prices[fill_time_idx + lookback_window]

    adverse_move_bps = abs(mid_post_fill - fill_price) * 10_000.0 / fill_price

    return adverse_move_bps


def compute_inventory_cost(
    position: float,
    mid_price_change_bps: float,
    inventory_penalty_bps: float = 2.0,
) -> float:
    """
    Compute cost of holding inventory.
    """

    if position == 0:
        return 0.0

    inventory_cost = abs(position) * inventory_penalty_bps * (1 + abs(position) * 0.1)

    return inventory_cost
