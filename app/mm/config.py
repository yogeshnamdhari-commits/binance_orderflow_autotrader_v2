from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

#: Authoritative experiment configuration. config.py defines the schema and
#: schema defaults only; backtests must load this JSON file explicitly so the
#: exact config hash can be recorded with every result.
CONFIG_JSON_DEFAULT = "app/mm/config.json"


@dataclass
class V20Config:
    """V20 market-making configuration schema."""

    symbol: str = "BTCUSDT"
    quote_interval_ms: int = 100
    base_half_spread_bps: float = 1.5
    max_half_spread_bps: float = 2.5
    inventory_target: float = 0.0
    inventory_penalty_bps: float = 2.0
    max_position_notional_usd: float = 5000.0
    quote_size_usd: float = 100.0
    maker_fee_bps: float = 2.0
    maker_rebate_bps: float = 0.0
    taker_fee_bps: float = 4.0
    live_order_submission: bool = False
    cancel_on_adverse_selection: bool = True
    adverse_selection_threshold_bps: float = 0.75
    min_top_level_qty: float = 0.0

    # Candidate-only microstructure controls. Defaults are disabled so the
    # production configuration is unchanged until a candidate passes OOS.
    toxicity_filter_enabled: bool = False
    toxicity_imbalance_threshold: float = 0.65
    toxicity_flow_threshold: float = 0.60
    microprice_skew_bps: float = 1.0
    flow_window_ms: int = 1000

    @classmethod
    def from_json(cls, filepath: str) -> V20Config:
        return cls.load_authoritative(filepath)[0]

    @classmethod
    def load_authoritative(cls, filepath: str) -> tuple[V20Config, str]:
        path = Path(filepath)
        if not path.is_file():
            raise FileNotFoundError(
                f"Authoritative V20 config not found: {filepath}."
            )
        with open(path) as f:
            data = json.load(f)
        allowed = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        config = cls(**allowed)
        return config, config_sha256(filepath)

    def canonical_dict(self) -> dict:
        from dataclasses import asdict
        return {k: v for k, v in asdict(self).items() if not k.startswith("comment")}


def canonical_config_dict(filepath: str) -> dict:
    with open(filepath) as f:
        data = json.load(f)
    return {k: data[k] for k in sorted(data) if not k.startswith("comment")}


def config_sha256(filepath: str) -> str:
    canonical = canonical_config_dict(filepath)
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()
