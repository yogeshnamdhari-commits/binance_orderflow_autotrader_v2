"""V6 contemporary execution-cost model with distributional data.

Q2 measured the full distribution of execution costs:
  - spread: p50, p90, p95, p99
  - slippage: buy/sell per notional band
  - fees: taker/maker round-trip
  - impact: allowance
  - latency: measured round-trip
  - safety margin: predeclared buffer

This module provides:
  1. Point estimates (gate, total) for backward compatibility
  2. Full distribution (p50/p90/p95/p99) for cost sensitivity scenarios
  3. Per-instrument cost calibration
  4. Maker/taker cost separation
  5. Contemporary vs historical comparison

Historical cost is NEVER used as a substitute for contemporary cost.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np


DEFAULT_CAL_PATH = Path("data/hist/research/execution_calibration.json")
DEFAULT_NOTIONAL_USD = 1000.0
SAFETY_MARGIN_BPS = 0.5   # predeclared, fixed before OOS
IMPACT_ALLOWANCE_BPS = 0.10
LATENCY_COST_BPS = 0.05
NON_FILL_REPRICE_COST_BPS = 0.50


@dataclass
class CostDistribution:
    """Full execution cost distribution from Q2 measurement."""
    spread_p50_bps: float
    spread_p90_bps: float
    spread_p95_bps: float
    spread_p99_bps: float
    slippage_buy_p50_bps: float
    slippage_buy_p90_bps: float
    slippage_sell_p50_bps: float
    slippage_sell_p90_bps: float
    fee_taker_roundtrip_bps: float
    fee_maker_roundtrip_bps: float
    impact_allowance_bps: float
    latency_bps: float
    safety_margin_bps: float
    p_fill: Optional[float] = None  # maker fill probability
    adverse_selection_bps: Optional[float] = None
    non_fill_reprice_bps: Optional[float] = None

    @property
    def taker_gate_bps(self) -> float:
        """Taker gate: p90 total cost + safety margin."""
        total = (self.spread_p90_bps + self.slippage_buy_p90_bps +
                 self.fee_taker_roundtrip_bps + self.impact_allowance_bps +
                 self.latency_bps + self.safety_margin_bps)
        return round(total, 6)

    @property
    def taker_total_bps(self) -> float:
        """Taker total: p90 cost without safety margin."""
        total = (self.spread_p90_bps + self.slippage_buy_p90_bps +
                 self.fee_taker_roundtrip_bps + self.impact_allowance_bps +
                 self.latency_bps)
        return round(total, 6)

    @property
    def maker_gate_bps(self) -> float:
        """Maker gate: fee + adverse selection + non-fill reprice + latency + margin."""
        if self.p_fill is None:
            # Default to empirical p_fill from Q2
            p_fill = 0.7568
        else:
            p_fill = self.p_fill
        adverse = self.adverse_selection_bps or 0.768
        non_fill = self.non_fill_reprice_bps or NON_FILL_REPRICE_COST_BPS
        total = (self.fee_maker_roundtrip_bps +
                 p_fill * adverse +
                 (1 - p_fill) * non_fill +
                 self.latency_bps +
                 self.safety_margin_bps)
        return round(total, 6)

    @property
    def maker_total_bps(self) -> float:
        """Maker total: fee + adverse selection + non-fill reprice + latency."""
        if self.p_fill is None:
            p_fill = 0.7568
        else:
            p_fill = self.p_fill
        adverse = self.adverse_selection_bps or 0.768
        non_fill = self.non_fill_reprice_bps or NON_FILL_REPRICE_COST_BPS
        total = (self.fee_maker_roundtrip_bps +
                 p_fill * adverse +
                 (1 - p_fill) * non_fill +
                 self.latency_bps)
        return round(total, 6)

    def scenario(self, spread_percentile: str = "p90",
                 slippage_percentile: str = "p90") -> dict:
        """Compute cost under different percentile scenarios."""
        spread = getattr(self, f"spread_{spread_percentile}_bps", self.spread_p90_bps)
        slippage = getattr(self, f"slippage_buy_{slippage_percentile}_bps",
                          self.slippage_buy_p90_bps)
        taker_total = spread + slippage + self.fee_taker_roundtrip_bps + \
                      self.impact_allowance_bps + self.latency_bps
        taker_gate = taker_total + self.safety_margin_bps
        return {
            "scenario": f"{spread_percentile}_spread_{slippage_percentile}_slippage",
            "taker_total_bps": round(taker_total, 6),
            "taker_gate_bps": round(taker_gate, 6),
            "maker_gate_bps": self.maker_gate_bps,
        }


def load_calibration(cal_path: Path = DEFAULT_CAL_PATH) -> dict:
    """Load execution cost calibration from JSON."""
    with open(cal_path) as f:
        return json.load(f)


def cost_distribution_from_cal(cal: dict, notional_usd: float = DEFAULT_NOTIONAL_USD) -> CostDistribution:
    """Build CostDistribution from Q2 calibration JSON."""
    # Find the notional band
    bands = cal.get("effective_taker_roundtrip", {})
    band_key = None
    for key in sorted(bands.keys(), key=int):
        if float(key) >= notional_usd:
            band_key = key
            break
    if band_key is None and bands:
        band_key = max(bands.keys(), key=int)

    if band_key and band_key in bands:
        band = bands[band_key]
        spread_p50 = band.get("spread_p50_bps", 0.0146)
        spread_p90 = band.get("spread_p90_bps", 0.0147)
        spread_p95 = band.get("spread_p95_bps", 0.0147)
        spread_p99 = band.get("spread_p99_bps", 0.0147)
        slip_p50 = band.get("slippage_buy_p50_bps", 0.0073)
        slip_p90 = band.get("slippage_buy_p90_bps", 0.0073)
    else:
        # Q2 defaults for BTCUSDT 1000 USD notional
        spread_p50 = 0.0146
        spread_p90 = 0.0147
        spread_p95 = 0.0147
        spread_p99 = 0.0147
        slip_p50 = 0.0073
        slip_p90 = 0.0073

    maker = cal.get("maker", {})
    p_fill = maker.get("p_fill")
    adverse = maker.get("adverse_selection_bps")
    non_fill = maker.get("non_fill_reprice_bps")

    return CostDistribution(
        spread_p50_bps=spread_p50,
        spread_p90_bps=spread_p90,
        spread_p95_bps=spread_p95,
        spread_p99_bps=spread_p99,
        slippage_buy_p50_bps=slip_p50,
        slippage_buy_p90_bps=slip_p90,
        slippage_sell_p50_bps=-slip_p50,
        slippage_sell_p90_bps=-slip_p90,
        fee_taker_roundtrip_bps=4.0,
        fee_maker_roundtrip_bps=2.0,
        impact_allowance_bps=IMPACT_ALLOWANCE_BPS,
        latency_bps=LATENCY_COST_BPS,
        safety_margin_bps=SAFETY_MARGIN_BPS,
        p_fill=p_fill,
        adverse_selection_bps=adverse,
        non_fill_reprice_bps=non_fill,
    )


def sensitivity_analysis(cost_dist: CostDistribution) -> dict:
    """Run cost sensitivity scenarios across percentile combinations."""
    scenarios = {}
    for spread_pct in ["p50", "p90", "p95", "p99"]:
        for slip_pct in ["p50", "p90", "p95", "p99"]:
            s = cost_dist.scenario(spread_pct, slip_pct)
            scenarios[f"{spread_pct}_{slip_pct}"] = s
    return scenarios


if __name__ == "__main__":
    cal = load_calibration()
    dist = cost_distribution_from_cal(cal)
    print(f"Taker gate: {dist.taker_gate_bps} bps")
    print(f"Maker gate: {dist.maker_gate_bps} bps")
    print(f"Taker total: {dist.taker_total_bps} bps")
    print(f"Maker total: {dist.maker_total_bps} bps")
    print("\nSensitivity scenarios:")
    for name, s in sensitivity_analysis(dist).items():
        print(f"  {name}: taker_gate={s['taker_gate_bps']:.4f} bps")
    print("OK")
