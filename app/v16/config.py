"""V16 configuration — event-time order-flow with walk-forward validation."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json


@dataclass(frozen=True)
class V16Config:
    version: str = "V16-queue-aware-event-time"
    experiment_id: str = "V16-20260908"
    symbol: str = "BTCUSDT"
    exchange: str = "BINANCE_FUTURES"
    product: str = "PERPETUAL"
    live_trading_enabled: bool = False

    prediction_horizon_ms: int = 10000
    feature_window_ms: int = 10000
    feature_cadence_ms: int = 1000

    maker_rebate_bps: float = -2.0
    taker_fee_bps: float = 5.0
    slippage_bps: float = 0.1
    adverse_selection_bps: float = 0.3
    latency_bps: float = 0.1
    exit_cost_bps: float = 3.0
    non_fill_opportunity_cost_bps: float = 0.5

    model_return_type: str = "gbr"
    model_fill_type: str = "logistic"
    n_estimators: int = 200
    max_depth: int = 4
    learning_rate: float = 0.1
    random_state: int = 42

    walk_forward_n_folds: int = 5
    walk_forward_train_pct: float = 0.6
    walk_forward_val_pct: float = 0.2
    walk_forward_forward_pct: float = 0.2
    min_obs_per_fold: int = 100
    min_trades_forward: int = 100
    min_observations_calibration: int = 100
    min_observations_forward: int = 50

    position_size_btc: float = 0.01
    max_holding_hours: float = 8.0
    stop_loss_bps: float = 50.0
    take_profit_bps: float = 50.0

    calibration_data_dir: str = "data/v16/calibration"
    forward_data_dir: str = "data/v16/forward"
    archive_dir: str = "archive/v16"

    @classmethod
    def config_hash(cls) -> str:
        fields = {
            "version": cls.version,
            "prediction_horizon_ms": cls.prediction_horizon_ms,
            "model_return_type": cls.model_return_type,
            "model_fill_type": cls.model_fill_type,
            "maker_rebate_bps": cls.maker_rebate_bps,
            "taker_fee_bps": cls.taker_fee_bps,
            "walk_forward_n_folds": cls.walk_forward_n_folds,
            "n_estimators": cls.n_estimators,
            "max_depth": cls.max_depth,
        }
        return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()[:16]

    @property
    def maker_entry_cost_bps(self) -> float:
        return self.maker_rebate_bps + self.slippage_bps + self.adverse_selection_bps + self.latency_bps

    @property
    def taker_entry_cost_bps(self) -> float:
        return self.taker_fee_bps + self.slippage_bps + self.adverse_selection_bps + self.latency_bps

    @property
    def total_roundtrip_cost_bps(self) -> float:
        return self.maker_entry_cost_bps + self.exit_cost_bps
