"""V15 configuration — execution-aware order-flow with regime filter."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json


@dataclass(frozen=True)
class V15Config:
    version: str = "V15-execution-aware"
    experiment_id: str = "V15-20260907"
    symbol: str = "BTCUSDT"
    exchange: str = "BINANCE_FUTURES"
    product: str = "PERPETUAL"
    live_trading_enabled: bool = False

    # Horizons
    prediction_horizon_ms: int = 10000
    horizons_tested_ms: tuple[int, ...] = (2000, 5000, 10000)
    feature_window_ms: int = 10000
    feature_cadence_ms: int = 1000

    # Execution (maker/taker router)
    maker_rebate_bps: float = -2.0
    taker_fee_bps: float = 5.0
    slippage_bps: float = 0.1
    adverse_selection_bps: float = 0.3
    latency_bps: float = 0.1
    exit_cost_bps: float = 3.0
    maker_fill_probability: float = 0.75
    safety_margin_bps: float = 1.0

    # Regime filter
    regime_filter_enabled: bool = True
    vol_regime_threshold_pct: float = 50.0  # top 50% vol
    liquidity_regime_threshold_pct: float = 50.0  # top 50% liquidity

    # Model
    model_type: str = "gbr"  # GradientBoostingRegressor
    n_estimators: int = 200
    max_depth: int = 4
    learning_rate: float = 0.1
    random_state: int = 42

    # Risk
    position_size_btc: float = 0.01
    max_holding_hours: float = 8.0
    stop_loss_bps: float = 50.0
    take_profit_bps: float = 50.0

    # Data
    calibration_data_dir: str = "data/v15/calibration"
    forward_data_dir: str = "data/v15/forward"
    archive_dir: str = "archive/v15"
    min_observations_calibration: int = 100
    min_observations_forward: int = 50
    min_trades_forward: int = 50

    @classmethod
    def config_hash(cls) -> str:
        fields = {
            "version": cls.version,
            "prediction_horizon_ms": cls.prediction_horizon_ms,
            "model_type": cls.model_type,
            "maker_rebate_bps": cls.maker_rebate_bps,
            "taker_fee_bps": cls.taker_fee_bps,
            "safety_margin_bps": cls.safety_margin_bps,
            "regime_filter_enabled": cls.regime_filter_enabled,
            "n_estimators": cls.n_estimators,
            "max_depth": cls.max_depth,
        }
        return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()[:16]

    @property
    def entry_cost_bps(self) -> float:
        maker = self.maker_rebate_bps + self.slippage_bps + self.adverse_selection_bps + self.latency_bps
        taker = self.taker_fee_bps + self.slippage_bps + self.adverse_selection_bps + self.latency_bps
        return self.maker_fill_probability * maker + (1 - self.maker_fill_probability) * taker

    @property
    def total_roundtrip_cost_bps(self) -> float:
        return self.entry_cost_bps + self.exit_cost_bps

    @property
    def breakeven_threshold_bps(self) -> float:
        return self.total_roundtrip_cost_bps + self.safety_margin_bps
