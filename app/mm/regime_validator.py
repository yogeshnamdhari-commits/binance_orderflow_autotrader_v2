from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass
class RegimeResult:
    """Results for a single volatility regime."""

    regime_id: int
    pnl_bps: float
    fills: int
    cancels: int
    inventory_max: float
    inventory_final: float
    gate_pass: bool
    reason: str


def validate_per_regime(
    mm_results: dict,
    min_pnl_bps: float = 100.0,
) -> list[RegimeResult]:
    """
    Validate that EACH regime is independently profitable.
    """

    results = []

    for regime_id in [0, 1, 2]:
        regime_data = mm_results.get(f"regime_{regime_id}", {})

        if not regime_data:
            results.append(RegimeResult(
                regime_id=regime_id,
                pnl_bps=0.0,
                fills=0,
                cancels=0,
                inventory_max=0.0,
                inventory_final=0.0,
                gate_pass=False,
                reason="no_data",
            ))
            continue

        pnl_bps = regime_data.get("pnl_bps", 0.0)
        fills = regime_data.get("fills", 0)
        cancels = regime_data.get("cancels", 0)
        inv_max = regime_data.get("inventory_max", 0.0)
        inv_final = regime_data.get("inventory_final", 0.0)

        gate_pass = pnl_bps > min_pnl_bps and inv_max < 0.5

        reason = ""
        if not gate_pass:
            if pnl_bps <= min_pnl_bps:
                reason = f"pnl_too_low ({pnl_bps:.2f} < {min_pnl_bps})"
            elif inv_max > 0.5:
                reason = f"inventory_breach ({inv_max:.4f} > 0.5)"
        else:
            reason = "pass"

        results.append(RegimeResult(
            regime_id=regime_id,
            pnl_bps=pnl_bps,
            fills=fills,
            cancels=cancels,
            inventory_max=inv_max,
            inventory_final=inv_final,
            gate_pass=gate_pass,
            reason=reason,
        ))

    return results
