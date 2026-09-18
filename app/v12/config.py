"""V12 research experiment — funding-aware order-flow strategy.

Independent configuration, model, calibration, and validation from V10/V11.
Economic mechanism: order-flow signal + funding rate income > execution costs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class V12Config:
    """Frozen V12 configuration — pre-registered, immutable."""
    symbol: str = "BTCUSDT"
    market: str = "USDT-M"
    exchange: str = "BINANCE_FUTURES"
    product: str = "PERPETUAL"
    leverage: float = 1.0
    live_trading_enabled: bool = False

    # Signal parameters
    signal_horizon_ms: int = 500
    feature_window_ms: int = 1000
    prediction_horizon_ms: int = 500

    # Execution parameters
    taker_fee_bps: float = 5.0  # Binance BTCUSDT taker fee (0.05%)
    maker_fee_bps: float = 2.0  # Binance BTCUSDT maker fee (0.02%)
    slippage_bps: float = 0.5
    adverse_selection_bps: float = 0.5
    latency_bps: float = 0.1
    funding_threshold_bps: float = 5.0  # Min positive funding to justify entry

    # Position parameters
    position_size_btc: float = 0.01
    max_holding_hours: float = 16.0
    stop_loss_bps: float = 50.0
    take_profit_bps: float = 50.0

    # Data paths
    calibration_data_dir: str = "data/v12/calibration"
    forward_data_dir: str = "data/v12/forward"
    research_data_dir: str = "data/research/v12"
    archive_dir: str = "archive/v12"

    # Model parameters (simple linear baseline — no overfitting)
    model_type: str = "ridge"
    regularization_c: float = 1.0
    n_bins: int = 20

    # Validation
    min_observations_calibration: int = 100
    min_observations_forward: int = 100
    alpha: float = 0.05
    min_effect_size: float = 0.2

    @classmethod
    def config_hash(cls) -> str:
        import hashlib
        import json
        c = cls()
        data = json.dumps({k: v for k, v in c.__dict__.items()}, sort_keys=True)
        return hashlib.sha256(data.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class V12EconomicDecomposition:
    """Per-trade economic decomposition."""
    signal_edge_bps: float
    funding_income_bps: float
    spread_paid_bps: float
    taker_fee_bps: float
    slippage_bps: float
    adverse_selection_bps: float
    exit_cost_bps: float
    gross_ev_bps: float
    total_cost_bps: float
    net_ev_bps: float
    hold_duration_hours: float
    signal_confidence: float


@dataclass(frozen=True)
class V12Signal:
    """V12 signal with full economic context."""
    ts_ms: int
    side: str  # "BUY", "SELL", "NO_TRADE"
    signal_edge_bps: float
    signal_confidence: float
    funding_rate_annual: float
    funding_income_bps: float
    predicted_return_bps: float
    features: dict[str, float]
    rationale: str
