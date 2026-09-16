"""V14 configuration — 10s horizon, maker/taker-aware execution."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json


@dataclass(frozen=True)
class V14Config:
    version: str = "V14-orderflow-10s-maker-taker"
    experiment_id: str = "V14-20260907"
    symbol: str = "BTCUSDT"
    exchange: str = "BINANCE_FUTURES"
    product: str = "PERPETUAL"
    live_trading_enabled: bool = False

    signal_horizon_ms: int = 10000
    feature_window_ms: int = 10000
    prediction_horizon_ms: int = 10000
    feature_cadence_ms: int = 1000

    # Execution (maker/taker-aware, Rule 11)
    maker_rebate_bps: float = -2.0
    taker_fee_bps: float = 5.0
    slippage_bps: float = 0.1
    adverse_selection_bps: float = 0.3
    latency_bps: float = 0.1
    exit_cost_bps: float = 3.0
    maker_fill_probability: float = 0.75
    funding_threshold_bps: float = 1.0

    position_size_btc: float = 0.01
    max_holding_hours: float = 8.0
    stop_loss_bps: float = 50.0
    take_profit_bps: float = 50.0

    model_type: str = "logistic"
    regularization_c: float = 1.0
    random_state: int = 42

    min_observations_calibration: int = 100
    min_observations_forward: int = 50
    alpha: float = 0.05
    min_effect_size: float = 0.2

    calibration_data_dir: str = "data/v14/calibration"
    forward_data_dir: str = "data/v14/forward"
    archive_dir: str = "archive/v14"

    @classmethod
    def config_hash(cls) -> str:
        fields = {
            "version": cls.version,
            "signal_horizon_ms": cls.signal_horizon_ms,
            "prediction_horizon_ms": cls.prediction_horizon_ms,
            "maker_rebate_bps": cls.maker_rebate_bps,
            "taker_fee_bps": cls.taker_fee_bps,
            "slippage_bps": cls.slippage_bps,
            "adverse_selection_bps": cls.adverse_selection_bps,
            "latency_bps": cls.latency_bps,
            "exit_cost_bps": cls.exit_cost_bps,
            "maker_fill_probability": cls.maker_fill_probability,
            "regularization_c": cls.regularization_c,
            "random_state": cls.random_state,
        }
        return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()[:16]

    @property
    def entry_cost_bps(self) -> float:
        # maker entry: rebate + low slippage + adverse + latency (probability-weighted)
        maker_cost = self.maker_rebate_bps + self.slippage_bps + self.adverse_selection_bps + self.latency_bps
        taker_cost = self.taker_fee_bps + self.slippage_bps + self.adverse_selection_bps + self.latency_bps
        return self.maker_fill_probability * maker_cost + (1 - self.maker_fill_probability) * taker_cost

    @property
    def total_roundtrip_cost_bps(self) -> float:
        return self.entry_cost_bps + self.exit_cost_bps
