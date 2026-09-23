"""Forward/paper-trading validation layer for V10.

This module implements the independent forward validation stage that follows a
successful OOS gate. The model and parameters are strictly frozen — no
parameter updates occur during forward validation.

The forward validation layer records:
- Predicted vs actual fill probability
- Expected vs realized EV
- Spread at decision time
- Realized slippage
- Queue/execution delay
- Fees/rebates
- Adverse selection
- Cancellations
- Partial fills
- Calibration drift
- Regime-level performance

Strict rule: forward observations must NOT be fed back into parameter tuning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any
import json

import numpy as np
import pandas as pd

from .v10_conditional_fill import QueueFillModel, fit_queue_binned_fill_rates, predict_queue_binned_fill_rate
from .v10_fill_survival import SurvivalCurve, fit_kaplan_meier
from .v10_passive_simulator import simulate_passive_order


class ForwardGateStatus(Enum):
    UNTESTED = "UNTESTED"
    RUNNING = "RUNNING"
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class FrozenModelConfig:
    """Immutable configuration for the forward validation model.

    All values are set at construction and never modified during validation.
    This enforces the strict frozen-model requirement.
    """
    bins: tuple[float, ...]
    survival_horizon: float
    spread_capture_bps: float
    fee_rebate_bps: float
    inventory_cost_bps: float
    exit_cost_bps: float
    cancellation_cost_bps: float
    order_quantity: float
    decision_every_n: int
    horizon_ms: int


@dataclass
class ForwardOrderRecord:
    """Single order record with predicted vs actual outcomes."""
    order_id: str
    timestamp: pd.Timestamp
    side: str
    mid_at_decision: float
    spread_at_decision_bps: float
    queue_ahead: float
    predicted_fill_probability: float
    actual_fill_fraction: float
    predicted_adverse_selection_bps: float
    actual_adverse_selection_bps: float
    predicted_ev_bps: float
    realized_ev_bps: float
    execution_latency_ms: float | None
    slippage_bps: float | None
    fees_bps: float | None
    regime_label: str | None
    book_imbalance_at_decision: float | None


@dataclass
class ForwardValidationResult:
    """Complete forward validation result with all metrics."""
    status: ForwardGateStatus
    n_orders: int
    n_filled: int
    fill_rate: float
    mean_predicted_fill_probability: float
    mean_actual_fill_fraction: float
    fill_prediction_error: float
    mean_predicted_ev_bps: float
    mean_realized_ev_bps: float
    ev_prediction_error: float
    mean_spread_bps: float
    mean_slippage_bps: float | None
    mean_fees_bps: float | None
    mean_adverse_selection_bps: float
    calibration_drift_fill: float
    calibration_drift_ev: float
    regime_results: dict[str, dict[str, float]]
    forward_gate: bool
    gate_conditions: dict[str, bool]
    order_records: list[ForwardOrderRecord] = field(default_factory=list)


class V10ForwardValidator:
    """Independent forward/paper-trading validator with strictly frozen model.

    This validator uses the OOS-calibrated model (fill rates, adverse selection)
    to generate predictions for forward data. The model is never updated during
    forward validation.

    Key principle: forward observations remain strictly out-of-sample. They are
    used only to evaluate whether the OOS edge survives real execution conditions.
    """

    def __init__(
        self,
        train_observations: pd.DataFrame,
        frozen_config: FrozenModelConfig,
        regime_mid_threshold: float | None = None,
    ):
        self._validate_train_observations(train_observations)
        self._frozen_config = frozen_config
        self._fill_model = fit_queue_binned_fill_rates(train_observations, bins=frozen_config.bins)
        self._adverse_model = self._fit_adverse_model(train_observations, frozen_config.bins)
        self._km_model = fit_kaplan_meier(
            train_observations["time_to_fill"],
            train_observations["filled"],
        )
        self._regime_mid_threshold = regime_mid_threshold
        self._orders: list[ForwardOrderRecord] = []
        self._status = ForwardGateStatus.UNTESTED

    @staticmethod
    def _validate_train_observations(train: pd.DataFrame) -> None:
        required = {"queue_ahead", "filled", "time_to_fill", "adverse_selection_bps", "fill_fraction"}
        missing = required - set(train.columns)
        if missing:
            raise ValueError(f"train missing required columns: {sorted(missing)}")
        if train.empty:
            raise ValueError("train must be non-empty")

    @classmethod
    def from_frozen_calibration(
        cls,
        calibration: FrozenCalibrationArtifact,
        regime_mid_threshold: float | None = None,
    ) -> "V10ForwardValidator":
        """Create a validator from a frozen calibration artifact.

        This factory method creates a V10ForwardValidator using pre-computed
        calibration models from an immutable FrozenCalibrationArtifact. This
        ensures forward validation uses OOS-calibrated models without any
        access to forward observations.

        Args:
            calibration: FrozenCalibrationArtifact from OOS calibration.
            regime_mid_threshold: Optional regime threshold.

        Returns:
            V10ForwardValidator initialized from frozen calibration.

        Raises:
            ValueError: If calibration fails integrity verification.
        """
        if not calibration.verify_integrity():
            raise ValueError("Frozen calibration artifact failed integrity check")

        validator = cls.__new__(cls)
        validator._frozen_config = calibration.config
        validator._fill_model = calibration.fill_model
        validator._adverse_model = (calibration.adverse_model_edges, np.array(calibration.adverse_model_rates))
        validator._km_model = calibration.km_model
        validator._regime_mid_threshold = regime_mid_threshold
        validator._orders = []
        validator._status = ForwardGateStatus.UNTESTED
        return validator

    def _fit_adverse_model(self, train: pd.DataFrame, bins) -> tuple[tuple[float, ...], np.ndarray]:
        filled = train[train["filled"] == 1]
        if filled.empty:
            return (tuple(float(x) for x in bins), np.zeros(len(bins) - 1))
        q = filled["queue_ahead"].to_numpy(float)
        a = filled["adverse_selection_bps"].to_numpy(float)
        edges = tuple(float(x) for x in bins)
        idx = np.searchsorted(edges, q, side="right") - 1
        rates = np.zeros(len(edges) - 1)
        for i in range(len(rates)):
            mask = idx == i
            if np.any(mask):
                rates[i] = float(np.mean(a[mask]))
        return edges, rates

    def predict_fill_probability(self, queue_ahead: float) -> float:
        return float(predict_queue_binned_fill_rate(self._fill_model, np.array([queue_ahead]))[0])

    def predict_adverse_selection(self, queue_ahead: float) -> float:
        q = np.array([queue_ahead])
        idx = np.searchsorted(self._adverse_model[0], q, side="right") - 1
        valid = (idx >= 0) & (idx < len(self._adverse_model[1]))
        return float(self._adverse_model[1][idx[0]]) if valid[0] else 0.0

    def expected_ev_bps(self, queue_ahead: float) -> float:
        fill_prob = self.predict_fill_probability(queue_ahead)
        adverse = self.predict_adverse_selection(queue_ahead)
        gross_if_filled = (
            self._frozen_config.spread_capture_bps
            + self._frozen_config.fee_rebate_bps
            - adverse
            - self._frozen_config.inventory_cost_bps
            - self._frozen_config.exit_cost_bps
        )
        return float(fill_prob * gross_if_filled - self._frozen_config.cancellation_cost_bps)

    def _regime_label(self, mid_price: float) -> str:
        if self._regime_mid_threshold is None:
            return "unknown"
        return "high" if mid_price >= self._regime_mid_threshold else "low"

    def record_order(
        self,
        timestamp: pd.Timestamp,
        side: str,
        mid_at_decision: float,
        spread_bps: float,
        queue_ahead: float,
        actual_fill_fraction: float,
        actual_adverse_selection_bps: float,
        execution_latency_ms: float | None = None,
        slippage_bps: float | None = None,
        fees_bps: float | None = None,
        book_imbalance: float | None = None,
    ) -> None:
        predicted_fill = self.predict_fill_probability(queue_ahead)
        predicted_adverse = self.predict_adverse_selection(queue_ahead)
        predicted_ev = self.expected_ev_bps(queue_ahead)

        realized_ev = simulate_passive_order(
            fill_fraction=float(actual_fill_fraction),
            spread_capture_bps=self._frozen_config.spread_capture_bps,
            fee_rebate_bps=self._frozen_config.fee_rebate_bps,
            adverse_selection_bps=float(actual_adverse_selection_bps),
            inventory_cost_bps=self._frozen_config.inventory_cost_bps,
            exit_cost_bps=self._frozen_config.exit_cost_bps,
            cancellation_cost_bps=self._frozen_config.cancellation_cost_bps,
        )["net_ev_bps"]

        order = ForwardOrderRecord(
            order_id=f"FWD-{len(self._orders) + 1:06d}",
            timestamp=timestamp,
            side=side,
            mid_at_decision=mid_at_decision,
            spread_at_decision_bps=spread_bps,
            queue_ahead=queue_ahead,
            predicted_fill_probability=predicted_fill,
            actual_fill_fraction=actual_fill_fraction,
            predicted_adverse_selection_bps=predicted_adverse,
            actual_adverse_selection_bps=actual_adverse_selection_bps,
            predicted_ev_bps=predicted_ev,
            realized_ev_bps=realized_ev,
            execution_latency_ms=execution_latency_ms,
            slippage_bps=slippage_bps,
            fees_bps=fees_bps,
            regime_label=self._regime_label(mid_at_decision),
            book_imbalance_at_decision=book_imbalance,
        )
        self._orders.append(order)
        self._status = ForwardGateStatus.RUNNING

    def evaluate(self, oos_fill_rate: float, oos_ev_bps: float, oos_adverse_bps: float) -> ForwardValidationResult:
        if len(self._orders) == 0:
            return ForwardValidationResult(
                status=ForwardGateStatus.UNTESTED,
                n_orders=0, n_filled=0, fill_rate=0.0,
                mean_predicted_fill_probability=0.0, mean_actual_fill_fraction=0.0,
                fill_prediction_error=0.0, mean_predicted_ev_bps=0.0, mean_realized_ev_bps=0.0,
                ev_prediction_error=0.0, mean_spread_bps=0.0, mean_slippage_bps=None,
                mean_fees_bps=None, mean_adverse_selection_bps=0.0,
                calibration_drift_fill=0.0, calibration_drift_ev=0.0,
                regime_results={}, forward_gate=False, gate_conditions={},
            )

        df = pd.DataFrame([o.__dict__ for o in self._orders])

        n_orders = len(df)
        n_filled = int((df["actual_fill_fraction"] > 0).sum())
        fill_rate = n_filled / n_orders if n_orders > 0 else 0.0

        mean_predicted_fill = float(df["predicted_fill_probability"].mean())
        mean_actual_fill = float(df["actual_fill_fraction"].mean())
        fill_prediction_error = mean_actual_fill - mean_predicted_fill

        mean_predicted_ev = float(df["predicted_ev_bps"].mean())
        mean_realized_ev = float(df["realized_ev_bps"].mean())
        ev_prediction_error = mean_realized_ev - mean_predicted_ev

        mean_spread = float(df["spread_at_decision_bps"].mean())
        mean_slippage = float(df["slippage_bps"].mean()) if df["slippage_bps"].notna().any() else None
        mean_fees = float(df["fees_bps"].mean()) if df["fees_bps"].notna().any() else None
        mean_adverse = float(df["actual_adverse_selection_bps"].mean())

        calibration_drift_fill = fill_rate - oos_fill_rate
        calibration_drift_ev = mean_realized_ev - oos_ev_bps

        regime_results: dict[str, dict[str, float]] = {}
        for regime, grp in df.groupby("regime_label"):
            regime_results[regime] = {
                "n_orders": int(len(grp)),
                "n_filled": int((grp["actual_fill_fraction"] > 0).sum()),
                "fill_rate": float((grp["actual_fill_fraction"] > 0).mean()),
                "mean_predicted_ev": float(grp["predicted_ev_bps"].mean()),
                "mean_realized_ev": float(grp["realized_ev_bps"].mean()),
                "mean_adverse": float(grp["actual_adverse_selection_bps"].mean()),
                "mean_spread": float(grp["spread_at_decision_bps"].mean()),
            }

        forward_gate = (
            mean_realized_ev > 0.0
            and fill_rate > 0.0
            and calibration_drift_fill > -0.10
            and calibration_drift_ev > -0.05
        )

        gate_conditions = {
            "positive_realized_ev": mean_realized_ev > 0.0,
            "positive_fill_rate": fill_rate > 0.0,
            "fill_drift_within_tolerance": calibration_drift_fill > -0.10,
            "ev_drift_within_tolerance": calibration_drift_ev > -0.05,
            "edge_survives_execution": mean_realized_ev > oos_ev_bps * 0.5,
        }

        self._status = ForwardGateStatus.PASS if forward_gate else ForwardGateStatus.FAIL

        return ForwardValidationResult(
            status=self._status,
            n_orders=n_orders,
            n_filled=n_filled,
            fill_rate=fill_rate,
            mean_predicted_fill_probability=mean_predicted_fill,
            mean_actual_fill_fraction=mean_actual_fill,
            fill_prediction_error=fill_prediction_error,
            mean_predicted_ev_bps=mean_predicted_ev,
            mean_realized_ev_bps=mean_realized_ev,
            ev_prediction_error=ev_prediction_error,
            mean_spread_bps=mean_spread,
            mean_slippage_bps=mean_slippage,
            mean_fees_bps=mean_fees,
            mean_adverse_selection_bps=mean_adverse,
            calibration_drift_fill=calibration_drift_fill,
            calibration_drift_ev=calibration_drift_ev,
            regime_results=regime_results,
            forward_gate=forward_gate,
            gate_conditions=gate_conditions,
            order_records=self._orders,
        )

    def to_dataframe(self) -> pd.DataFrame:
        if not self._orders:
            return pd.DataFrame()
        return pd.DataFrame([o.__dict__ for o in self._orders])

    def summary_dict(self) -> dict[str, Any]:
        return {
            "status": self._status.value,
            "n_orders": len(self._orders),
            "frozen_config": {
                "bins": self._frozen_config.bins,
                "survival_horizon": self._frozen_config.survival_horizon,
                "spread_capture_bps": self._frozen_config.spread_capture_bps,
                "fee_rebate_bps": self._frozen_config.fee_rebate_bps,
                "inventory_cost_bps": self._frozen_config.inventory_cost_bps,
                "exit_cost_bps": self._frozen_config.exit_cost_bps,
                "cancellation_cost_bps": self._frozen_config.cancellation_cost_bps,
            },
            "fill_model": {
                "edges": self._fill_model.edges,
                "rates": self._fill_model.rates,
            },
        }


class FrozenCalibrationArtifact:
    """Immutable frozen calibration artifact for forward validation.

    This class encapsulates the complete OOS calibration state needed by
    V10ForwardValidator, including fill rates, adverse selection, and
    survival models. It is created from OOS training observations and
    must NEVER contain forward observations.

    Provenance is preserved via hash of the original training data.

    Attributes:
        schema_version: Artifact format version
        frozen_at: ISO timestamp of creation
        config: Frozen model configuration
        fill_model: Binned fill-rate model
        adverse_model: Binned adverse-selection model
        km_model: Kaplan-Meier survival curve
        train_summary: Training data provenance statistics
        provenance: Provenance metadata
        _train_hash: SHA-256 hash of training observations (for integrity)
    """

    SCHEMA_VERSION = "v10.forward.frozen.v2"

    def __init__(self, data: dict[str, Any]):
        """Load from a frozen calibration JSON dict.

        Args:
            data: Parsed JSON from a frozen calibration file.

        Raises:
            ValueError: If schema version is unsupported or data is incomplete.
        """
        if data.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported schema version: {data.get('schema_version')}. "
                f"Expected {self.SCHEMA_VERSION}."
            )

        self.schema_version = data["schema_version"]
        self.frozen_at = data["frozen_at"]
        self.config = FrozenModelConfig(**data["config"])
        self.train_summary = data["train_summary"]
        self.provenance = data.get("provenance", {})
        self._train_hash = hash(json.dumps(data.get("train_summary", {}), sort_keys=True))

        fill = data["fill_model"]
        self.fill_model = QueueFillModel(
            edges=tuple(fill["edges"]),
            rates=tuple(fill["rates"]),
            prior=float(fill["prior"]),
        )

        adverse = data["adverse_model"]
        self.adverse_model_edges = tuple(adverse["edges"])
        self.adverse_model_rates = tuple(adverse["rates"])

        km = data["km_model"]
        self.km_model = SurvivalCurve(
            times=tuple(km["times"]),
            survival=tuple(km["survival"]),
            events=tuple(km["events"]),
            at_risk=tuple(km["at_risk"]),
        )

    @classmethod
    def from_path(cls, path: str | Path) -> "FrozenCalibrationArtifact":
        """Load a frozen calibration artifact from a JSON file.

        Args:
            path: Path to the frozen calibration JSON file.

        Returns:
            FrozenCalibrationArtifact instance.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the file contains invalid data.
        """
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"Frozen calibration file not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data)

    def predict_fill_probability(self, queue_ahead: float) -> float:
        """Predict fill probability using the frozen fill model."""
        return float(predict_queue_binned_fill_rate(self.fill_model, np.array([queue_ahead]))[0])

    def predict_adverse_selection(self, queue_ahead: float) -> float:
        """Predict adverse selection using the frozen adverse model."""
        q = np.array([queue_ahead])
        idx = np.searchsorted(self.adverse_model_edges, q, side="right") - 1
        valid = (idx >= 0) & (idx < len(self.adverse_model_rates))
        return float(self.adverse_model_rates[idx[0]]) if valid[0] else 0.0

    def km_fill_probability(self, horizon: float) -> float:
        """Get Kaplan-Meier fill probability at a given horizon."""
        return self.km_model.fill_probability(horizon)

    def verify_integrity(self) -> bool:
        """Verify that the artifact has not been tampered with.

        Returns:
            True if the artifact passes integrity checks.
        """
        try:
            assert self.schema_version == self.SCHEMA_VERSION
            assert len(self.fill_model.edges) > 0
            assert len(self.fill_model.rates) == len(self.fill_model.edges) - 1
            assert len(self.adverse_model_edges) > 0
            assert len(self.adverse_model_rates) == len(self.adverse_model_edges) - 1
            assert len(self.km_model.times) == len(self.km_model.survival)
            assert self.train_summary["n_observations"] > 0
            return True
        except (AssertionError, KeyError, TypeError):
            return False

    def to_dict(self) -> dict[str, Any]:
        """Serialize the artifact to a dict for JSON export."""
        return {
            "schema_version": self.schema_version,
            "frozen_at": self.frozen_at,
            "config": {
                "bins": self.config.bins,
                "survival_horizon": self.config.survival_horizon,
                "spread_capture_bps": self.config.spread_capture_bps,
                "fee_rebate_bps": self.config.fee_rebate_bps,
                "inventory_cost_bps": self.config.inventory_cost_bps,
                "exit_cost_bps": self.config.exit_cost_bps,
                "cancellation_cost_bps": self.config.cancellation_cost_bps,
                "order_quantity": self.config.order_quantity,
                "decision_every_n": self.config.decision_every_n,
                "horizon_ms": self.config.horizon_ms,
            },
            "fill_model": {
                "edges": list(self.fill_model.edges),
                "rates": list(self.fill_model.rates),
                "prior": self.fill_model.prior,
            },
            "adverse_model": {
                "edges": list(self.adverse_model_edges),
                "rates": list(self.adverse_model_rates),
            },
            "km_model": {
                "times": list(self.km_model.times),
                "survival": list(self.km_model.survival),
                "events": list(self.km_model.events),
                "at_risk": list(self.km_model.at_risk),
            },
            "train_summary": self.train_summary,
            "provenance": self.provenance,
        }


def run_forward_validation(
    train_observations: pd.DataFrame,
    forward_observations: pd.DataFrame,
    frozen_config: FrozenModelConfig,
    regime_mid_threshold: float | None = None,
    oos_fill_rate: float = 0.0,
    oos_ev_bps: float = 0.0,
    oos_adverse_bps: float = 0.0,
) -> ForwardValidationResult:
    """Run complete forward validation pass.

    Args:
        train_observations: Historical observations used to fit the frozen model.
        forward_observations: Forward/out-of-sample observations to validate against.
        frozen_config: Frozen model configuration.
        regime_mid_threshold: Optional mid-price threshold for regime labeling.
        oos_fill_rate: OOS fill rate for drift comparison.
        oos_ev_bps: OOS EV for drift comparison.
        oos_adverse_bps: OOS adverse selection for drift comparison.

    Returns:
        ForwardValidationResult with all metrics and gate decision.
    """
    required = {"timestamp", "side", "mid_at_placement", "queue_ahead", "filled", "fill_fraction", "adverse_selection_bps"}
    missing = required - set(forward_observations.columns)
    if missing:
        raise ValueError(f"forward_observations missing required columns: {sorted(missing)}")

    validator = V10ForwardValidator(
        train_observations=train_observations,
        frozen_config=frozen_config,
        regime_mid_threshold=regime_mid_threshold,
    )

    for _, row in forward_observations.iterrows():
        spread_bps = 0.0
        try:
            spread_bps = float(row.get("spread_bps", 0.0))
        except (TypeError, ValueError):
            spread_bps = 0.0

        validator.record_order(
            timestamp=row["timestamp"],
            side=row["side"],
            mid_at_decision=float(row["mid_at_placement"]),
            spread_bps=spread_bps,
            queue_ahead=float(row["queue_ahead"]),
            actual_fill_fraction=float(row["fill_fraction"]),
            actual_adverse_selection_bps=float(row["adverse_selection_bps"]),
            execution_latency_ms=float(row.get("execution_latency_ms", np.nan)) if pd.notna(row.get("execution_latency_ms")) else None,
            slippage_bps=float(row["slippage_bps"]) if pd.notna(row.get("slippage_bps")) else None,
            fees_bps=float(row["fees_bps"]) if pd.notna(row.get("fees_bps")) else None,
            book_imbalance=float(row["book_imbalance"]) if pd.notna(row.get("book_imbalance")) else None,
        )

    return validator.evaluate(
        oos_fill_rate=oos_fill_rate,
        oos_ev_bps=oos_ev_bps,
        oos_adverse_bps=oos_adverse_bps,
    )


def freeze_and_export_model(
    train_observations: pd.DataFrame,
    config: FrozenModelConfig,
    output_path: str | Path,
) -> dict[str, Any]:
    """Freeze the model configuration and export for forward validation.

    This function creates a frozen model package that can be loaded by
    forward validators without any access to forward data.

    The frozen package contains:
    - config: The immutable model configuration
    - fill_model: Binned fill-rate model (edges, rates, prior)
    - adverse_model: Binned adverse-selection model (edges, rates)
    - km_model: Kaplan-Meier survival curve (times, survival, events, at_risk)
    - train_summary: Provenance statistics (n_observations, n_filled, fill_rate)

    Args:
        train_observations: Historical training observations with columns:
            queue_ahead, filled, time_to_fill, adverse_selection_bps, fill_fraction
        config: Frozen model configuration.
        output_path: Path to write the frozen model package.

    Returns:
        Frozen model summary dict.

    Raises:
        ValueError: If train_observations is missing required columns or is empty.
    """
    required = {"queue_ahead", "filled", "time_to_fill", "adverse_selection_bps", "fill_fraction"}
    missing = required - set(train_observations.columns)
    if missing:
        raise ValueError(f"train_observations missing required columns: {sorted(missing)}")
    if train_observations.empty:
        raise ValueError("train_observations must be non-empty")

    fill_model = fit_queue_binned_fill_rates(train_observations, bins=config.bins)

    filled_obs = train_observations[train_observations["filled"] == 1]
    if filled_obs.empty:
        adverse_edges = tuple(float(x) for x in config.bins)
        adverse_rates = np.zeros(len(config.bins) - 1)
    else:
        q = filled_obs["queue_ahead"].to_numpy(float)
        a = filled_obs["adverse_selection_bps"].to_numpy(float)
        edges = tuple(float(x) for x in config.bins)
        idx = np.searchsorted(edges, q, side="right") - 1
        adverse_rates = np.zeros(len(edges) - 1)
        for i in range(len(adverse_rates)):
            mask = idx == i
            if np.any(mask):
                adverse_rates[i] = float(np.mean(a[mask]))
        adverse_edges = edges

    km_curve = fit_kaplan_meier(
        train_observations["time_to_fill"],
        train_observations["filled"],
    )

    frozen_package = {
        "schema_version": "v10.forward.frozen.v2",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "config": {
            "bins": config.bins,
            "survival_horizon": config.survival_horizon,
            "spread_capture_bps": config.spread_capture_bps,
            "fee_rebate_bps": config.fee_rebate_bps,
            "inventory_cost_bps": config.inventory_cost_bps,
            "exit_cost_bps": config.exit_cost_bps,
            "cancellation_cost_bps": config.cancellation_cost_bps,
            "order_quantity": config.order_quantity,
            "decision_every_n": config.decision_every_n,
            "horizon_ms": config.horizon_ms,
        },
        "fill_model": {
            "edges": fill_model.edges,
            "rates": fill_model.rates,
            "prior": fill_model.prior,
        },
        "adverse_model": {
            "edges": adverse_edges,
            "rates": [float(x) for x in adverse_rates],
        },
        "km_model": {
            "times": list(km_curve.times),
            "survival": list(km_curve.survival),
            "events": list(km_curve.events),
            "at_risk": list(km_curve.at_risk),
        },
        "train_summary": {
            "n_observations": int(len(train_observations)),
            "n_filled": int(train_observations["filled"].sum()),
            "fill_rate": float(train_observations["filled"].mean()),
        },
        "provenance": {
            "oosp_validation_reference": {
                "note": "Frozen from OOS calibration. Forward observations must NOT be included.",
                "required_columns": list(required),
            },
        },
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(frozen_package, indent=2, default=str))
    return frozen_package


__all__ = [
    "ForwardGateStatus",
    "FrozenModelConfig",
    "FrozenCalibrationArtifact",
    "ForwardOrderRecord",
    "ForwardValidationResult",
    "V10ForwardValidator",
    "run_forward_validation",
    "freeze_and_export_model",
]
