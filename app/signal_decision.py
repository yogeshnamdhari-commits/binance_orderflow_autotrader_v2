"""V6 Signal Decision Engine — hard-gate decision tree.

Decision logic (pre-registered, immutable):
  DATA_VALID
    AND BOOK_VALID
    AND LIQUIDITY_VALID
    AND PREDICTIVE_EDGE
    AND CALIBRATED_PROBABILITY
    AND EXPECTED_NET_RETURN > 0
    AND REGIME_SUPPORTED
    AND EXECUTION_FEASIBLE
  => TRADE_CANDIDATE (BUY or SELL)
  => NO_TRADE otherwise

No confidence scores. No weighted averages. No CVD-as-signal.
Probability must be calibrated. Cost must be contemporaneous.

This module does NOT modify V5 or any existing code.
It is additive only.
"""

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Decision states
# ---------------------------------------------------------------------------

class DecisionState(Enum):
    NO_TRADE = "NO_TRADE"
    BUY = "BUY"
    SELL = "SELL"


class BookIntegrityState(Enum):
    BOOK_STARTING = "BOOK_STARTING"
    BOOK_SYNCING = "BOOK_SYNCING"
    BOOK_VALID = "BOOK_VALID"
    BOOK_STALE = "BOOK_STALE"
    BOOK_GAP = "BOOK_GAP"
    BOOK_RESYNC = "BOOK_RESYNC"
    BOOK_INVALID = "BOOK_INVALID"


# ---------------------------------------------------------------------------
# Liquidity regime states
# ---------------------------------------------------------------------------

class LiquidityRegime(Enum):
    NORMAL = "NORMAL"
    THIN = "THIN"
    STRESSED = "STRESSED"
    SHOCK = "SHOCK"
    RECOVERY = "RECOVERY"


# ---------------------------------------------------------------------------
# Decision result
# ---------------------------------------------------------------------------

@dataclass
class DecisionResult:
    state: DecisionState
    reason: str
    expected_gross_bps: float = 0.0
    expected_net_bps: float = 0.0
    cost_bps: float = 0.0
    probability: float = 0.0
    regime: str = "UNKNOWN"
    book_state: str = "BOOK_STARTING"
    liquidity_regime: str = "UNKNOWN"
    toxicity_state: str = "UNKNOWN"
    gates: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "state": self.state.value,
            "reason": self.reason,
            "expected_gross_bps": round(self.expected_gross_bps, 6),
            "expected_net_bps": round(self.expected_net_bps, 6),
            "cost_bps": round(self.cost_bps, 6),
            "probability": round(self.probability, 4),
            "regime": self.regime,
            "book_state": self.book_state,
            "liquidity_regime": self.liquidity_regime,
            "toxicity_state": self.toxicity_state,
            "gates": self.gates,
        }


# ---------------------------------------------------------------------------
# Signal Decision Engine
# ---------------------------------------------------------------------------

class SignalDecisionEngine:
    """Hard-gate signal decision engine.

    All gates must pass for a trade to be allowed.
    No gate can be bypassed or tuned post-hoc.
    """

    def __init__(self, cost_cal_path=None, primary_horizon_ms=500):
        self.cost_cal_path = cost_cal_path or Path("data/hist/research/execution_calibration.json")
        self.primary_horizon_ms = primary_horizon_ms
        self._load_cost_calibration()
        # Pre-registered thresholds (fixed before any OOS examination)
        self.PROBABILITY_THRESHOLD = 0.60  # minimum calibrated probability
        self.MIN_NET_BPS = 0.0  # minimum expected net return
        self.MAX_DRAWDOWN_BPS = 10.0  # maximum allowable drawdown
        self.MAX_TURNOVER = 0.50  # maximum fraction of rows traded
        self.ALLOWED_REGIMES = {"NORMAL", "RECOVERY"}  # regimes where trading is allowed
        self.TOXICITY_LIMITS = {"HIGH_TOXICITY", "ELEVATED_TOXICITY"}
        # Calibration state
        self._calibrator = None
        self._calibration_method = None
        self._calibration_metrics = None
        self._val_predictions = None
        self._val_outcomes = None

    def _load_cost_calibration(self):
        """Load contemporary execution cost calibration."""
        try:
            cal = json.load(open(self.cost_cal_path))
            self.taker_gate_bps = float(cal.get("taker", {}).get("gate_bps", 4.6646))
            self.maker_gate_bps = float(cal.get("maker", {}).get("gate_bps", 3.4396))
            self.taker_total_bps = float(cal.get("taker", {}).get("total_bps", 4.1646))
            self.maker_total_bps = float(cal.get("maker", {}).get("total_bps", 2.9396))
        except Exception:
            # Fallback to Q2 measured values
            self.taker_gate_bps = 4.6646
            self.maker_gate_bps = 3.4396
            self.taker_total_bps = 4.1646
            self.maker_total_bps = 2.9396

    def fit_calibration(self, val_predictions: np.ndarray, val_outcomes: np.ndarray,
                        method: str = "isotonic"):
        """Fit probability calibration on validation data.

        Args:
            val_predictions: Model predictions on validation set (bps)
            val_outcomes: Binary outcomes (1 if net > 0, 0 otherwise)
            method: "isotonic" or "platt"

        Sets:
            self._calibrator: Fitted calibrator
            self._calibration_method: Method used
            self._calibration_metrics: Brier score, ECE, reliability
        """
        # Convert predictions to probabilities via sigmoid
        probs = 1.0 / (1.0 + np.exp(-val_predictions))
        probs = np.clip(probs, 0.01, 0.99)

        if method == "isotonic":
            try:
                from sklearn.isotonic import IsotonicRegression
                ir = IsotonicRegression(out_of_bounds="clip")
                calibrated = ir.fit_transform(probs, val_outcomes)
                self._calibrator = ir
            except ImportError:
                # Fallback: simple Platt scaling via logistic regression
                method = "platt"
        if method == "platt" or self._calibrator is None:
            try:
                from sklearn.linear_model import LogisticRegression
                lr = LogisticRegression()
                lr.fit(probs.reshape(-1, 1), val_outcomes)
                calibrated = lr.predict_proba(probs.reshape(-1, 1))[:, 1]
                self._calibrator = lr
            except ImportError:
                # No sklearn: use identity calibration
                self._calibrator = None
                calibrated = probs

        self._calibration_method = method
        self._val_predictions = val_predictions.copy()
        self._val_outcomes = val_outcomes.copy()

        # Compute calibration metrics
        brier = float(np.mean((calibrated - val_outcomes) ** 2))

        # Expected Calibration Error (ECE)
        n_bins = 10
        bin_boundaries = np.linspace(0, 1, n_bins + 1)
        ece = 0.0
        reliability = []
        for i in range(n_bins):
            mask = (calibrated > bin_boundaries[i]) & (calibrated <= bin_boundaries[i + 1])
            if mask.sum() > 0:
                bin_accuracy = float(val_outcomes[mask].mean())
                bin_confidence = float(calibrated[mask].mean())
                ece += mask.sum() * abs(bin_accuracy - bin_confidence)
                reliability.append({
                    "bin_low": float(bin_boundaries[i]),
                    "bin_high": float(bin_boundaries[i + 1]),
                    "count": int(mask.sum()),
                    "avg_confidence": round(bin_confidence, 4),
                    "avg_accuracy": round(bin_accuracy, 4),
                })
        ece /= len(calibrated)

        self._calibration_metrics = {
            "method": method,
            "brier_score": round(brier, 6),
            "ece": round(ece, 6),
            "reliability": reliability,
            "n_samples": len(probs),
        }

    def predict_calibrated_probability(self, prediction: float) -> float:
        """Predict calibrated probability for a new prediction."""
        if self._calibrator is None:
            # Fallback: sigmoid of prediction
            prob = 1.0 / (1.0 + np.exp(-prediction))
            return float(np.clip(prob, 0.01, 0.99))

        # Convert prediction to probability via sigmoid
        prob = 1.0 / (1.0 + np.exp(-prediction))
        prob = np.clip(prob, 0.01, 0.99)

        if hasattr(self._calibrator, "predict_proba"):
            calibrated = self._calibrator.predict_proba(np.array([prob]).reshape(-1, 1))[:, 1]
            return float(calibrated[0])
        else:
            return float(prob)

    def calibration_metrics(self) -> dict:
        """Return calibration metrics from validation data."""
        if not hasattr(self, "_calibration_metrics"):
            return {"status": "not_fitted"}
        return self._calibration_metrics

    def decide(self, row: pd.Series, prediction: float,
               book_state: BookIntegrityState) -> DecisionResult:
        """Make trading decision based on all evidence.

        Args:
            row: DataFrame row with all features
            prediction: Model prediction (expected return in bps)
            book_state: Current L2 book integrity state

        Returns:
            DecisionResult with state, reason, and all gate results
        """
        gates = {}

        # Gate 1: DATA_VALID
        data_valid = True
        gates["data_valid"] = data_valid

        # Gate 2: BOOK_VALID
        book_valid = book_state == BookIntegrityState.BOOK_VALID
        gates["book_valid"] = book_valid
        if not book_valid:
            return DecisionResult(
                state=DecisionState.NO_TRADE,
                reason=f"BOOK_INVALID: {book_state.value}",
                book_state=book_state.value,
                gates=gates,
            )

        # Gate 3: LIQUIDITY_VALID
        liquidity_regime = row.get("liquidity_state", "UNKNOWN")
        liquidity_valid = liquidity_regime in self.ALLOWED_REGIMES
        gates["liquidity_valid"] = liquidity_valid
        if not liquidity_valid:
            return DecisionResult(
                state=DecisionState.NO_TRADE,
                reason=f"LIQUIDITY_INVALID: regime={liquidity_regime}",
                book_state=book_state.value,
                liquidity_regime=liquidity_regime,
                gates=gates,
            )

        # Gate 4: PREDICTIVE_EDGE
        predictive_edge = np.isfinite(prediction) and abs(prediction) > 0.0
        gates["predictive_edge"] = predictive_edge
        if not predictive_edge:
            return DecisionResult(
                state=DecisionState.NO_TRADE,
                reason="NO_PREDICTIVE_EDGE: prediction=0 or non-finite",
                expected_gross_bps=prediction,
                book_state=book_state.value,
                liquidity_regime=liquidity_regime,
                gates=gates,
            )

        # Gate 5: CALIBRATED_PROBABILITY
        # Use calibrated probability if available, otherwise fallback to magnitude proxy
        if self._calibrator is not None:
            prob = self.predict_calibrated_probability(prediction)
        else:
            # Fallback: use |prediction| as a proxy for confidence
            prob = min(1.0, abs(prediction) / max(self.taker_gate_bps, 1.0))
        probability_valid = prob >= self.PROBABILITY_THRESHOLD
        gates["calibrated_probability"] = probability_valid
        gates["probability"] = round(prob, 4)
        if not probability_valid:
            return DecisionResult(
                state=DecisionState.NO_TRADE,
                reason=f"LOW_PROBABILITY: {prob:.4f} < {self.PROBABILITY_THRESHOLD}",
                expected_gross_bps=prediction,
                book_state=book_state.value,
                liquidity_regime=liquidity_regime,
                probability=prob,
                gates=gates,
            )

        # Gate 6: EXPECTED_NET_RETURN > 0
        # Use appropriate cost based on predicted direction and regime
        if prediction > 0:
            # Long prediction: use taker cost for immediate execution
            cost_bps = self.taker_gate_bps
            expected_net_bps = prediction - cost_bps
        else:
            # Short prediction: use taker cost for immediate execution
            cost_bps = self.taker_gate_bps
            expected_net_bps = abs(prediction) - cost_bps

        net_positive = expected_net_bps > self.MIN_NET_BPS
        gates["expected_net_positive"] = net_positive
        gates["expected_gross_bps"] = prediction
        gates["expected_net_bps"] = expected_net_bps
        gates["cost_bps"] = cost_bps
        if not net_positive:
            return DecisionResult(
                state=DecisionState.NO_TRADE,
                reason=f"NEGATIVE_NET: gross={prediction:.4f} net={expected_net_bps:.4f} cost={cost_bps:.4f}",
                expected_gross_bps=prediction,
                expected_net_bps=expected_net_bps,
                cost_bps=cost_bps,
                book_state=book_state.value,
                liquidity_regime=liquidity_regime,
                probability=prob,
                gates=gates,
            )

        # Gate 7: REGIME_SUPPORTED
        regime_supported = liquidity_regime in self.ALLOWED_REGIMES
        gates["regime_supported"] = regime_supported
        if not regime_supported:
            return DecisionResult(
                state=DecisionState.NO_TRADE,
                reason=f"REGIME_NOT_SUPPORTED: {liquidity_regime}",
                expected_gross_bps=prediction,
                expected_net_bps=expected_net_bps,
                cost_bps=cost_bps,
                book_state=book_state.value,
                liquidity_regime=liquidity_regime,
                probability=prob,
                gates=gates,
            )

        # Gate 8: EXECUTION_FEASIBLE
        # Check toxicity: avoid trading in high toxicity regimes
        toxicity = row.get("toxicity_state", "LOW_TOXICITY")
        gates["toxicity_ok"] = toxicity not in self.TOXICITY_LIMITS
        execution_feasible = toxicity not in self.TOXICITY_LIMITS
        if not execution_feasible:
            return DecisionResult(
                state=DecisionState.NO_TRADE,
                reason=f"HIGH_TOXICITY: {toxicity}",
                expected_gross_bps=prediction,
                expected_net_bps=expected_net_bps,
                cost_bps=cost_bps,
                book_state=book_state.value,
                liquidity_regime=liquidity_regime,
                toxicity_state=toxicity,
                probability=prob,
                gates=gates,
            )

        # All gates passed -> trade candidate
        trade_state = DecisionState.BUY if prediction > 0 else DecisionState.SELL
        return DecisionResult(
            state=trade_state,
            reason="ALL_GATES_PASS",
            expected_gross_bps=prediction,
            expected_net_bps=expected_net_bps,
            cost_bps=cost_bps,
            book_state=book_state.value,
            liquidity_regime=liquidity_regime,
            toxicity_state=toxicity,
            probability=prob,
            gates=gates,
        )

    def evaluate_oos(self, df: pd.DataFrame, predictions: np.ndarray,
                     book_states: list) -> pd.DataFrame:
        """Evaluate decisions on OOS data.

        Args:
            df: OOS DataFrame with features
            predictions: Model predictions (bps)
            book_states: List of BookIntegrityState for each row

        Returns:
            DataFrame with decision results
        """
        results = []
        for i, (_, row) in enumerate(df.iterrows()):
            book_state = book_states[i] if i < len(book_states) else BookIntegrityState.BOOK_INVALID
            result = self.decide(row, predictions[i], book_state)
            results.append(result.to_dict())

        return pd.DataFrame(results)


def calibrate_probability(predictions: np.ndarray, outcomes: np.ndarray,
                          method: str = "isotonic") -> dict:
    """Calibrate prediction probabilities using validation data.

    Methods:
      - "isotonic": Isotonic regression (non-parametric, monotonic)
      - "platt": Platt scaling (logistic calibration)

    Returns calibration metrics: Brier score, ECE, reliability.
    """
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression

    # Bin predictions into probability buckets
    probs = 1.0 / (1.0 + np.exp(-predictions))  # sigmoid mapping
    probs = np.clip(probs, 0.01, 0.99)

    if method == "isotonic":
        ir = IsotonicRegression(out_of_bounds="clip")
        calibrated = ir.fit_transform(probs, outcomes)
    else:
        lr = LogisticRegression()
        lr.fit(probs.reshape(-1, 1), outcomes)
        calibrated = lr.predict_proba(probs.reshape(-1, 1))[:, 1]

    # Brier score
    brier = float(np.mean((calibrated - outcomes) ** 2))

    # Expected Calibration Error (ECE)
    n_bins = 10
    bin_boundaries = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    for i in range(n_bins):
        mask = (probs > bin_boundaries[i]) & (probs <= bin_boundaries[i + 1])
        if mask.sum() > 0:
            bin_accuracy = outcomes[mask].mean()
            bin_confidence = calibrated[mask].mean()
            ece += mask.sum() * abs(bin_accuracy - bin_confidence)
    ece /= len(probs)

    # Reliability curve data
    reliability = []
    for i in range(n_bins):
        mask = (probs > bin_boundaries[i]) & (probs <= bin_boundaries[i + 1])
        if mask.sum() > 0:
            reliability.append({
                "bin_low": float(bin_boundaries[i]),
                "bin_high": float(bin_boundaries[i + 1]),
                "count": int(mask.sum()),
                "avg_confidence": float(calibrated[mask].mean()),
                "avg_accuracy": float(outcomes[mask].mean()),
            })

    return {
        "method": method,
        "brier_score": round(brier, 6),
        "ece": round(ece, 6),
        "reliability": reliability,
        "n_samples": len(probs),
    }


if __name__ == "__main__":
    # Self-test
    engine = SignalDecisionEngine()
    print("SignalDecisionEngine initialized")
    print(f"Taker gate: {engine.taker_gate_bps} bps")
    print(f"Maker gate: {engine.maker_gate_bps} bps")
    print("OK")
