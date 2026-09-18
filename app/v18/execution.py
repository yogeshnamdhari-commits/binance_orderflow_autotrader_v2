from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionCost:
    maker_fee_bps: float
    taker_fee_bps: float
    spread_bps: float
    slippage_bps: float
    non_fill_opportunity_bps: float

    @property
    def maker_round_trip_bps(self) -> float:
        return 2.0 * self.maker_fee_bps + self.spread_bps + self.slippage_bps

    @property
    def taker_round_trip_bps(self) -> float:
        return 2.0 * self.taker_fee_bps + self.spread_bps + self.slippage_bps


def stressed_cost(cost: ExecutionCost, multiplier: float) -> ExecutionCost:
    if multiplier <= 0:
        raise ValueError("cost multiplier must be positive")
    return ExecutionCost(
        maker_fee_bps=cost.maker_fee_bps * multiplier,
        taker_fee_bps=cost.taker_fee_bps * multiplier,
        spread_bps=cost.spread_bps * multiplier,
        slippage_bps=cost.slippage_bps * multiplier,
        non_fill_opportunity_bps=cost.non_fill_opportunity_bps * multiplier,
    )
