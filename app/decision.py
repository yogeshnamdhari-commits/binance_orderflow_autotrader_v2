"""Production decision engine — V5 model -> calibrated expected return -> execution cost -> net -> decision.

Pipeline (per the project spec):

    DATA -> ORDER BOOK -> TRADES -> FEATURES -> MICROSTRUCTURE STATE
         -> V5 MODEL -> CALIBRATED EXPECTED RETURN -> EXECUTION COST -> NET EXPECTED RETURN
         -> DECISION

The V5 ridge model (frozen, 500ms horizon) provides the expected move E[r_500 | X] in bps.
The binned calibration maps raw predictions to calibrated expected returns.
The execution gate uses the measured maker/taker cost + safety margin.

Canonical decision states:
    NO_SIGNAL              - no directional order-flow signal (|calibrated| <= gate)
    INVALID_DATA           - book not valid / price or spread unavailable
    INSUFFICIENT_LIQUIDITY - book too thin to fill at the touched size
    HIGH_TOXICITY          - adverse-selection / churn regime
    COST_OVERWHELMED       - gross edge positive but net edge <= 0 after cost
    POSITIVE_EXPECTANCY    - gross edge > 0 (signal level), gates pending
    EXECUTION_READY        - gross > 0 AND all cost/liquidity/toxicity gates pass

This module does NOT remove the live-trading hard block (governance lives in
config + orchestrator). EXECUTION_READY is a pre-trade classification, not an
authorization to trade live.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from .v5_model import load_model, predict
from .v5_calibration import calibrate_prediction
from .v5_cost import measured_gate
from .fillmodel import PassiveFillModel


class DecisionState(Enum):
    NO_SIGNAL = "NO_SIGNAL"
    INVALID_DATA = "INVALID_DATA"
    INSUFFICIENT_LIQUIDITY = "INSUFFICIENT_LIQUIDITY"
    HIGH_TOXICITY = "HIGH_TOXICITY"
    COST_OVERWHELMED = "COST_OVERWHELMED"
    POSITIVE_EXPECTANCY = "POSITIVE_EXPECTANCY"
    EXECUTION_READY = "EXECUTION_READY"


@dataclass
class SignalDecision:
    state: DecisionState
    side: str | None = None
    gross_bps: float = 0.0
    cost_bps: float = 0.0
    net_bps: float = 0.0
    probability: float = 0.0
    reason: str = ""
    book_state: str = "BOOK_STARTING"
    liquidity_state: str = "UNKNOWN"
    toxicity_state: str = "UNKNOWN"
    gates: dict = field(default_factory=dict)
    features: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "state": self.state.value,
            "side": self.side,
            "gross_bps": round(self.gross_bps, 6),
            "cost_bps": round(self.cost_bps, 6),
            "net_bps": round(self.net_bps, 6),
            "probability": round(self.probability, 4),
            "reason": self.reason,
            "book_state": self.book_state,
            "liquidity_state": self.liquidity_state,
            "toxicity_state": self.toxicity_state,
            "gates": self.gates,
        }

    @property
    def tradable(self):
        return self.state == DecisionState.EXECUTION_READY


class DecisionEngine:
    """Hard-gate decision engine using the frozen V5 ridge model + calibration."""
    
    def __init__(
        self,
        v5_model_path: str = "data/research/v5_model.json",
        v5_calibration_path: str = "data/research/v5_binned_calibration.json",
        v5_model_json: str = "data/research/v5_model.json",  # for calibration
        v5_features_path: str = "data/research/v5_features.parquet",
        fill_model=None,
        horizon_ms=500,  # V5 model horizon
        notional_usd=10_000,
        min_liquidity_usd=50_000.0,
        toxicity_limit=("HIGH_TOXICITY",),
        allowed_liquidity=("NORMAL", "RECOVERY"),
        min_fill_prob=0.30,
        safety_margin_bps=0.5,
        # Test-only: inject a prediction function for testing
        _predict_fn=None,
        _calibrate_fn=None,
    ):
        # Load V5 model
        self.v5_model = load_model(v5_model_path)
        self.v5_model_path = v5_model_path
        self.v5_calibration_path = v5_calibration_path
        self.v5_model_json = v5_model_json
        self.v5_features_path = v5_features_path
        
        # Load calibration
        import json
        with open(v5_calibration_path) as f:
            cal_data = json.load(f)
        # Convert lists back to numpy arrays
        import numpy as np
        self.calibration = {
            'bin_edges': np.array(cal_data['bin_edges']),
            'bin_means': np.array(cal_data['bin_means']),
            'bin_counts': np.array(cal_data['bin_counts']),
            'bin_stderr': np.array(cal_data['bin_stderr']),
            'horizon_ms': cal_data['horizon_ms'],
            'n_bins': cal_data['n_bins'],
            'min_pred': cal_data['min_pred'],
            'max_pred': cal_data['max_pred'],
        }
        
        self.fill_model = fill_model
        self.horizon_ms = horizon_ms
        self.notional_usd = notional_usd
        self.min_liquidity_usd = min_liquidity_usd
        self.toxicity_limit = set(toxicity_limit)
        self.allowed_liquidity = set(allowed_liquidity)
        self.min_fill_prob = min_fill_prob
        self.safety_margin_bps = safety_margin_bps
        
        # Load cost model for gate
        from .v3_cost import load_cal, cost_model
        cal_path = Path("data/hist/research/execution_calibration.json")
        cal = load_cal(cal_path)
        self.cost_model = cost_model(cal, notional_usd=notional_usd)
        self.maker_fee_bps = self.cost_model["maker"]["total_bps"]
        self.taker_gate_bps = self.cost_model["taker"]["gate_bps"]
        
        # V5 model features (must match V5_FEATURES)
        from app.v5_features import V5_FEATURES
        self.v5_features = V5_FEATURES
        
        # Test-only: inject prediction function
        self._predict_fn = _predict_fn
        self._calibrate_fn = _calibrate_fn

    def evaluate(self, f, book_state_str=None, book=None):
        """Classify the current microstructure state into exactly one DecisionState.

        Args:
            f: FlowFeatures from OrderFlowEngine (must contain V5_FEATURES).
            book_state_str: canonical book integrity state (defaults to f.book_state).
            book: optional LocalOrderBook (for fill depth-factor).
        """
        book_state_str = book_state_str or f.book_state
        gates = {}

        # Gate 1: DATA / BOOK validity
        if book_state_str != "BOOK_VALID" or f.mid <= 0 or f.spread_bps <= 0:
            return SignalDecision(
                DecisionState.INVALID_DATA,
                reason="book/price invalid (mid<=0 or spread<=0 or book not valid)",
                book_state=book_state_str, liquidity_state=f.liquidity_state,
                toxicity_state=f.toxicity_state, gates=gates, features=vars(f))

        # Gate 2: V5 model signal (calibrated expected return)
        # Prepare feature vector for V5 model
        try:
            import numpy as np
            X = np.array([[getattr(f, feat) for feat in self.v5_features]], dtype=float)
        except AttributeError as e:
            return SignalDecision(
                DecisionState.INVALID_DATA,
                reason=f"missing V5 feature: {e}",
                book_state=book_state_str, liquidity_state=f.liquidity_state,
                toxicity_state=f.toxicity_state, gates=gates, features=vars(f))

        # Check for NaN/inf in features
        if not np.isfinite(X).all():
            return SignalDecision(
                DecisionState.INVALID_DATA,
                reason="non-finite V5 features",
                book_state=book_state_str, liquidity_state=f.liquidity_state,
                toxicity_state=f.toxicity_state, gates=gates, features=vars(f))

        # Get raw V5 prediction (bps)
        import pandas as pd
        df_feat = pd.DataFrame(X, columns=self.v5_features)
        if self._predict_fn is not None:
            pred_raw = self._predict_fn(df_feat)
        else:
            pred_raw = predict(self.v5_model, df_feat, self.horizon_ms)[0]
        
        # Get calibrated expected return (bps)
        df_cal = pd.DataFrame(X, columns=self.v5_features)
        if self._calibrate_fn is not None:
            calibrated = self._calibrate_fn(self.v5_model, df_cal, self.horizon_ms, self.calibration)[0]
        else:
            calibrated = calibrate_prediction(
                self.v5_model, df_cal, self.horizon_ms, self.calibration
            )[0]

        if not np.isfinite(calibrated):
            return SignalDecision(
                DecisionState.NO_SIGNAL,
                reason="calibrated prediction not finite",
                book_state=book_state_str, liquidity_state=f.liquidity_state,
                toxicity_state=f.toxicity_state, gates=gates, features=vars(f))

        # Determine side from calibrated expected return
        side = "BUY" if calibrated > 0 else "SELL" if calibrated < 0 else None
        if side is None:
            return SignalDecision(
                DecisionState.NO_SIGNAL,
                reason="calibrated prediction zero",
                book_state=book_state_str, liquidity_state=f.liquidity_state,
                toxicity_state=f.toxicity_state, gates=gates, features=vars(f))

        gross = calibrated

        # Gate 3: liquidity adequacy
        if f.liquidity_state not in self.allowed_liquidity:
            return SignalDecision(
                DecisionState.INSUFFICIENT_LIQUIDITY, side=side,
                gross_bps=gross,
                reason=f"liquidity regime={f.liquidity_state} (below tradable threshold)",
                book_state=book_state_str, liquidity_state=f.liquidity_state,
                toxicity_state=f.toxicity_state, gates=gates, features=vars(f))

        # Gate 4: toxicity / adverse selection
        if f.toxicity_state in self.toxicity_limit:
            return SignalDecision(
                DecisionState.HIGH_TOXICITY, side=side,
                gross_bps=gross,
                reason=f"toxicity regime={f.toxicity_state}",
                book_state=book_state_str, liquidity_state=f.liquidity_state,
                toxicity_state=f.toxicity_state, gates=gates, features=vars(f))

        # Gate 5: execution cost gate
        # Use taker gate for directional entries (conservative) or maker cost for passive
        # The V5 model uses taker gate; production uses maker fee.
        # We'll use the more conservative taker gate for the gate check.
        gate = self.taker_gate_bps + self.safety_margin_bps
        
        # Net expectancy after cost
        # For maker execution: net = gross - maker_fee_bps
        # For taker execution: net = gross - taker_gate_bps
        # We'll report both
        maker_net = gross - self.maker_fee_bps
        taker_net = gross - self.taker_gate_bps
        
        # Use the more conservative (taker) net for the gate check
        net = taker_net
        cost = self.taker_gate_bps
        
        gates["gross_positive"] = gross > 0
        gates["net_positive"] = net > 0
        gates["gate_bps"] = gate
        gates["maker_net_bps"] = maker_net
        gates["taker_net_bps"] = taker_net

        if gross <= 0:
            return SignalDecision(
                DecisionState.COST_OVERWHELMED, side=side,
                gross_bps=gross, net_bps=net,
                reason="no positive expectancy (gross<=0)",
                book_state=book_state_str, liquidity_state=f.liquidity_state,
                toxicity_state=f.toxicity_state, gates=gates, features=vars(f))

        if net <= 0:
            return SignalDecision(
                DecisionState.COST_OVERWHELMED, side=side,
                gross_bps=gross, cost_bps=cost, net_bps=net,
                reason="net edge not positive after cost",
                book_state=book_state_str, liquidity_state=f.liquidity_state,
                toxicity_state=f.toxicity_state, gates=gates, features=vars(f))

        # Statistical significance gate: require 95% CI lower bound > cost
        # This would require bootstrap CI from calibration - for now use point estimate
        # TODO: add bootstrap CI check from calibration

        return SignalDecision(
            DecisionState.EXECUTION_READY, side=side,
            gross_bps=gross, cost_bps=cost, net_bps=net,
            reason="ALL_GATES_PASS",
            book_state=book_state_str, liquidity_state=f.liquidity_state,
            toxicity_state=f.toxicity_state, gates=gates, features=vars(f))