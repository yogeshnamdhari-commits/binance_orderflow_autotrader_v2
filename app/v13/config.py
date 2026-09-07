"""V13 configuration — frozen, immutable, pre-registered."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json


@dataclass(frozen=True)
class V13Config:
    """V13 experimental configuration.

    Key change from V12: prediction horizon 2000 ms (vs 500 ms), with
    order-flow-persistence features at the matching window.
    """
    version: str = "V13-orderflow-persistence-2s"
    experiment_id: str = "V13-20260907"
    symbol: str = "BTCUSDT"
    market: str = "USDT-M"
    exchange: str = "BINANCE_FUTURES"
    product: str = "PERPETUAL"

    signal_horizon_ms: int = 2000
    feature_window_ms: int = 2000
    prediction_horizon_ms: int = 2000

    taker_fee_bps: float = 5.0
    maker_fee_bps: float = 2.0
    slippage_bps: float = 0.5
    adverse_selection_bps: float = 0.5
    latency_bps: float = 0.1
    exit_cost_bps: float = 5.0
    funding_threshold_bps: float = 5.0

    position_size_btc: float = 0.01
    max_holding_hours: float = 8.0
    stop_loss_bps: float = 50.0
    take_profit_bps: float = 50.0

    model_type: str = "logistic"
    regularization_c: float = 1.0
    random_state: int = 42

    min_observations_calibration: int = 100
    min_observations_forward: int = 100
    alpha: float = 0.05
    min_effect_size: float = 0.2

    calibration_data_dir: str = "data/v13/calibration"
    forward_data_dir: str = "data/v13/forward"
    archive_dir: str = "archive/v13"

    @classmethod
    def config_hash(cls) -> str:
        fields = {
            "version": cls.version,
            "signal_horizon_ms": cls.signal_horizon_ms,
            "feature_window_ms": cls.feature_window_ms,
            "prediction_horizon_ms": cls.prediction_horizon_ms,
            "taker_fee_bps": cls.taker_fee_bps,
            "maker_fee_bps": cls.maker_fee_bps,
            "slippage_bps": cls.slippage_bps,
            "adverse_selection_bps": cls.adverse_selection_bps,
            "latency_bps": cls.latency_bps,
            "exit_cost_bps": cls.exit_cost_bps,
            "funding_threshold_bps": cls.funding_threshold_bps,
            "regularization_c": cls.regularization_c,
            "random_state": cls.random_state,
        }
        return hashlib.sha256(
            json.dumps(fields, sort_keys=True).encode()
        ).hexdigest()[:16]

    @classmethod
    def model_metadata(cls) -> dict:
        return {
            "version": cls.version,
            "experiment_id": cls.experiment_id,
            "hypothesis": (
                "Order-flow signed trade imbalance + order-book imbalance predict "
                "BTCUSDT 2s-ahead returns (persistence peak), where V12 at 500ms showed no signal."
            ),
            "config_hash": cls.config_hash(),
            "prediction_horizon_ms": cls.prediction_horizon_ms,
            "feature_window_ms": cls.feature_window_ms,
            "source_datasets": "NEW real Binance captures (not V12 forward data)",
            "creation_timestamp": "2026-09-07",
        }
