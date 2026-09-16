from __future__ import annotations

from dataclasses import dataclass


@dataclass
class V20Config:
    """V20 market-making configuration."""

    symbol: str = "BTCUSDT"
    quote_interval_ms: int = 100
    base_half_spread_bps: float = 1.5
    max_half_spread_bps: float = 2.5
    inventory_target: float = 0.0
    inventory_penalty_bps: float = 2.0
    max_position_notional_usd: float = 5000.0
    quote_size_usd: float = 100.0
    maker_fee_bps: float = 2.0
    taker_fee_bps: float = 4.0
    live_order_submission: bool = False
    cancel_on_adverse_selection: bool = True
    adverse_selection_threshold_bps: float = 0.75
    min_top_level_qty: float = 0.0

    @classmethod
    def from_json(cls, filepath: str) -> V20Config:
        """Load config from JSON file."""
        import json

        with open(filepath) as f:
            data = json.load(f)
        allowed = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**allowed)

