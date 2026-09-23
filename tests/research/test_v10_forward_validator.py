"""Tests for V10 forward/paper-trading validator."""

from __future__ import annotations

import json
import numpy as np
import pandas as pd
import pytest

from app.v10_forward_validator import (
    ForwardGateStatus,
    FrozenModelConfig,
    FrozenCalibrationArtifact,
    V10ForwardValidator,
    run_forward_validation,
    freeze_and_export_model,
)


def make_train_observations(n: int = 200, fill_rate: float = 0.15) -> pd.DataFrame:
    """Create synthetic training observations."""
    np.random.seed(42)
    obs = []
    for i in range(n):
        q = float(np.random.exponential(0.5))
        filled = 1 if np.random.random() < fill_rate else 0
        obs.append({
            "timestamp": pd.Timestamp("2025-01-01") + pd.Timedelta(seconds=i * 10),
            "side": "bid" if i % 2 == 0 else "ask",
            "mid_at_placement": 77000.0 + np.random.randn() * 100,
            "spread_bps": 0.013,
            "queue_ahead": q,
            "filled": filled,
            "fill_fraction": filled * np.random.uniform(0.8, 1.0),
            "adverse_selection_bps": np.random.randn() * 2.0 if filled else 0.0,
            "time_to_fill": np.random.uniform(100, 800) if filled else 1000.0,
        })
    return pd.DataFrame(obs)


def make_forward_observations(n: int = 50, fill_rate: float = 0.12) -> pd.DataFrame:
    """Create synthetic forward observations."""
    np.random.seed(99)
    obs = []
    for i in range(n):
        q = float(np.random.exponential(0.5))
        filled = 1 if np.random.random() < fill_rate else 0
        obs.append({
            "timestamp": pd.Timestamp("2025-02-01") + pd.Timedelta(seconds=i * 10),
            "side": "bid" if i % 2 == 0 else "ask",
            "mid_at_placement": 77000.0 + np.random.randn() * 100,
            "spread_bps": 0.013,
            "queue_ahead": q,
            "filled": filled,
            "fill_fraction": filled * np.random.uniform(0.8, 1.0),
            "adverse_selection_bps": np.random.randn() * 2.0 if filled else 0.0,
            "execution_latency_ms": np.random.uniform(10, 50) if filled else None,
            "slippage_bps": np.random.uniform(0.01, 0.05) if filled else None,
            "fees_bps": 0.1,
            "book_imbalance": np.random.randn() * 0.1,
        })
    return pd.DataFrame(obs)


class TestFrozenModelConfig:
    def test_config_is_frozen(self):
        config = FrozenModelConfig(
            bins=(0.0, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, float("inf")),
            survival_horizon=1000.0,
            spread_capture_bps=2.0,
            fee_rebate_bps=0.5,
            inventory_cost_bps=0.2,
            exit_cost_bps=0.3,
            cancellation_cost_bps=0.05,
            order_quantity=0.01,
            decision_every_n=10,
            horizon_ms=1000,
        )
        with pytest.raises(AttributeError):
            config.bins = (0.0, 0.1, 1.0)


class TestV10ForwardValidator:
    def test_validator_requires_train_columns(self):
        train = pd.DataFrame({"queue_ahead": [0.1, 0.2]})
        config = FrozenModelConfig(
            bins=(0.0, 0.1, 0.5, float("inf")),
            survival_horizon=1000.0,
            spread_capture_bps=2.0,
            fee_rebate_bps=0.5,
            inventory_cost_bps=0.2,
            exit_cost_bps=0.3,
            cancellation_cost_bps=0.05,
            order_quantity=0.01,
            decision_every_n=10,
            horizon_ms=1000,
        )
        with pytest.raises(ValueError, match="missing required columns"):
            V10ForwardValidator(train, config)

    def test_predict_fill_probability(self):
        train = make_train_observations(200)
        config = FrozenModelConfig(
            bins=(0.0, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, float("inf")),
            survival_horizon=1000.0,
            spread_capture_bps=2.0,
            fee_rebate_bps=0.5,
            inventory_cost_bps=0.2,
            exit_cost_bps=0.3,
            cancellation_cost_bps=0.05,
            order_quantity=0.01,
            decision_every_n=10,
            horizon_ms=1000,
        )
        validator = V10ForwardValidator(train, config)
        prob = validator.predict_fill_probability(0.05)
        assert 0.0 <= prob <= 1.0

    def test_predict_adverse_selection(self):
        train = make_train_observations(200)
        config = FrozenModelConfig(
            bins=(0.0, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, float("inf")),
            survival_horizon=1000.0,
            spread_capture_bps=2.0,
            fee_rebate_bps=0.5,
            inventory_cost_bps=0.2,
            exit_cost_bps=0.3,
            cancellation_cost_bps=0.05,
            order_quantity=0.01,
            decision_every_n=10,
            horizon_ms=1000,
        )
        validator = V10ForwardValidator(train, config)
        adverse = validator.predict_adverse_selection(0.05)
        assert isinstance(adverse, float)

    def test_expected_ev_bps(self):
        train = make_train_observations(200)
        config = FrozenModelConfig(
            bins=(0.0, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, float("inf")),
            survival_horizon=1000.0,
            spread_capture_bps=2.0,
            fee_rebate_bps=0.5,
            inventory_cost_bps=0.2,
            exit_cost_bps=0.3,
            cancellation_cost_bps=0.05,
            order_quantity=0.01,
            decision_every_n=10,
            horizon_ms=1000,
        )
        validator = V10ForwardValidator(train, config)
        ev = validator.expected_ev_bps(0.05)
        assert isinstance(ev, float)

    def test_record_order_and_evaluate(self):
        train = make_train_observations(200)
        config = FrozenModelConfig(
            bins=(0.0, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, float("inf")),
            survival_horizon=1000.0,
            spread_capture_bps=2.0,
            fee_rebate_bps=0.5,
            inventory_cost_bps=0.2,
            exit_cost_bps=0.3,
            cancellation_cost_bps=0.05,
            order_quantity=0.01,
            decision_every_n=10,
            horizon_ms=1000,
        )
        validator = V10ForwardValidator(train, config)

        for _, row in train.head(50).iterrows():
            validator.record_order(
                timestamp=row["timestamp"],
                side=row["side"],
                mid_at_decision=float(row["mid_at_placement"]),
                spread_bps=float(row["spread_bps"]),
                queue_ahead=float(row["queue_ahead"]),
                actual_fill_fraction=float(row["fill_fraction"]),
                actual_adverse_selection_bps=float(row["adverse_selection_bps"]),
            )

        result = validator.evaluate(oos_fill_rate=0.15, oos_ev_bps=0.18, oos_adverse_bps=1.5)
        assert result.n_orders == 50
        assert result.status in (ForwardGateStatus.PASS, ForwardGateStatus.FAIL)
        assert "fill_drift_within_tolerance" in result.gate_conditions
        assert "ev_drift_within_tolerance" in result.gate_conditions

    def test_regime_labeling(self):
        train = make_train_observations(200)
        config = FrozenModelConfig(
            bins=(0.0, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, float("inf")),
            survival_horizon=1000.0,
            spread_capture_bps=2.0,
            fee_rebate_bps=0.5,
            inventory_cost_bps=0.2,
            exit_cost_bps=0.3,
            cancellation_cost_bps=0.05,
            order_quantity=0.01,
            decision_every_n=10,
            horizon_ms=1000,
        )
        validator = V10ForwardValidator(train, config, regime_mid_threshold=77000.0)

        validator.record_order(
            timestamp=pd.Timestamp("2025-01-01"),
            side="bid",
            mid_at_decision=78000.0,
            spread_bps=0.013,
            queue_ahead=0.05,
            actual_fill_fraction=0.5,
            actual_adverse_selection_bps=1.0,
        )
        validator.record_order(
            timestamp=pd.Timestamp("2025-01-02"),
            side="ask",
            mid_at_decision=76000.0,
            spread_bps=0.013,
            queue_ahead=0.05,
            actual_fill_fraction=0.5,
            actual_adverse_selection_bps=1.0,
        )

        df = validator.to_dataframe()
        assert "high" in df["regime_label"].values
        assert "low" in df["regime_label"].values


class TestRunForwardValidation:
    def test_run_forward_validation(self):
        train = make_train_observations(200)
        forward = make_forward_observations(50)
        config = FrozenModelConfig(
            bins=(0.0, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, float("inf")),
            survival_horizon=1000.0,
            spread_capture_bps=2.0,
            fee_rebate_bps=0.5,
            inventory_cost_bps=0.2,
            exit_cost_bps=0.3,
            cancellation_cost_bps=0.05,
            order_quantity=0.01,
            decision_every_n=10,
            horizon_ms=1000,
        )
        result = run_forward_validation(
            train_observations=train,
            forward_observations=forward,
            frozen_config=config,
            oos_fill_rate=0.15,
            oos_ev_bps=0.18,
            oos_adverse_bps=1.5,
        )
        assert result.n_orders == 50
        assert result.status in (ForwardGateStatus.PASS, ForwardGateStatus.FAIL)

    def test_run_forward_validation_missing_columns(self):
        train = make_train_observations(200)
        forward = pd.DataFrame({"timestamp": [pd.Timestamp("2025-01-01")]})
        config = FrozenModelConfig(
            bins=(0.0, 0.1, float("inf")),
            survival_horizon=1000.0,
            spread_capture_bps=2.0,
            fee_rebate_bps=0.5,
            inventory_cost_bps=0.2,
            exit_cost_bps=0.3,
            cancellation_cost_bps=0.05,
            order_quantity=0.01,
            decision_every_n=10,
            horizon_ms=1000,
        )
        with pytest.raises(ValueError, match="missing required columns"):
            run_forward_validation(train, forward, config)


class TestFreezeAndExportModel:
    def test_freeze_and_export_model(self, tmp_path):
        train = make_train_observations(200)
        config = FrozenModelConfig(
            bins=(0.0, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, float("inf")),
            survival_horizon=1000.0,
            spread_capture_bps=2.0,
            fee_rebate_bps=0.5,
            inventory_cost_bps=0.2,
            exit_cost_bps=0.3,
            cancellation_cost_bps=0.05,
            order_quantity=0.01,
            decision_every_n=10,
            horizon_ms=1000,
        )
        output_path = tmp_path / "frozen_model.json"
        result = freeze_and_export_model(train, config, output_path)

        assert output_path.exists()
        assert result["schema_version"] == "v10.forward.frozen.v2"
        assert "fill_model" in result
        assert "adverse_model" in result
        assert "km_model" in result
        assert result["config"]["spread_capture_bps"] == 2.0
        assert result["fill_model"]["edges"] == (0.0, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, float("inf"))
        assert len(result["adverse_model"]["rates"]) == 7
        assert len(result["km_model"]["times"]) > 0


class TestFrozenCalibrationArtifact:
    def test_load_from_dict(self, tmp_path):
        train = make_train_observations()
        config = FrozenModelConfig(
            bins=(0.0, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, float("inf")),
            survival_horizon=1000.0,
            spread_capture_bps=2.0,
            fee_rebate_bps=0.5,
            inventory_cost_bps=0.2,
            exit_cost_bps=0.3,
            cancellation_cost_bps=0.05,
            order_quantity=0.01,
            decision_every_n=10,
            horizon_ms=1000,
        )
        output_path = tmp_path / "frozen_model.json"
        freeze_and_export_model(train, config, output_path)

        data = json.loads(output_path.read_text())
        artifact = FrozenCalibrationArtifact(data)

        assert artifact.schema_version == "v10.forward.frozen.v2"
        assert artifact.config.spread_capture_bps == 2.0
        assert artifact.train_summary["n_observations"] == len(train)
        assert artifact.verify_integrity()

    def test_load_from_path(self, tmp_path):
        train = make_train_observations()
        config = FrozenModelConfig(
            bins=(0.0, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, float("inf")),
            survival_horizon=1000.0,
            spread_capture_bps=2.0,
            fee_rebate_bps=0.5,
            inventory_cost_bps=0.2,
            exit_cost_bps=0.3,
            cancellation_cost_bps=0.05,
            order_quantity=0.01,
            decision_every_n=10,
            horizon_ms=1000,
        )
        output_path = tmp_path / "frozen_model.json"
        freeze_and_export_model(train, config, output_path)

        artifact = FrozenCalibrationArtifact.from_path(output_path)
        assert artifact.verify_integrity()
        assert artifact.predict_fill_probability(0.05) >= 0.0

    def test_unsupported_schema_version(self):
        data = {
            "schema_version": "v99.forward.frozen.v999",
            "frozen_at": "2026-01-01T00:00:00+00:00",
            "config": {},
            "fill_model": {"edges": [], "rates": [], "prior": 0.5},
            "adverse_model": {"edges": [], "rates": []},
            "km_model": {"times": [], "survival": [], "events": [], "at_risk": []},
            "train_summary": {"n_observations": 0, "n_filled": 0, "fill_rate": 0.0},
        }
        with pytest.raises(ValueError, match="Unsupported schema version"):
            FrozenCalibrationArtifact(data)

    def test_predict_methods(self, tmp_path):
        train = make_train_observations()
        config = FrozenModelConfig(
            bins=(0.0, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, float("inf")),
            survival_horizon=1000.0,
            spread_capture_bps=2.0,
            fee_rebate_bps=0.5,
            inventory_cost_bps=0.2,
            exit_cost_bps=0.3,
            cancellation_cost_bps=0.05,
            order_quantity=0.01,
            decision_every_n=10,
            horizon_ms=1000,
        )
        output_path = tmp_path / "frozen_model.json"
        freeze_and_export_model(train, config, output_path)

        artifact = FrozenCalibrationArtifact.from_path(output_path)
        fp = artifact.predict_fill_probability(0.05)
        assert 0.0 <= fp <= 1.0
        ae = artifact.predict_adverse_selection(0.05)
        assert isinstance(ae, float)
        km_fp = artifact.km_fill_probability(1000.0)
        assert 0.0 <= km_fp <= 1.0


class TestV10ForwardValidatorFromFrozen:
    def test_from_frozen_calibration(self, tmp_path):
        train = make_train_observations()
        config = FrozenModelConfig(
            bins=(0.0, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, float("inf")),
            survival_horizon=1000.0,
            spread_capture_bps=2.0,
            fee_rebate_bps=0.5,
            inventory_cost_bps=0.2,
            exit_cost_bps=0.3,
            cancellation_cost_bps=0.05,
            order_quantity=0.01,
            decision_every_n=10,
            horizon_ms=1000,
        )
        output_path = tmp_path / "frozen_model.json"
        freeze_and_export_model(train, config, output_path)

        artifact = FrozenCalibrationArtifact.from_path(output_path)
        validator = V10ForwardValidator.from_frozen_calibration(artifact)

        fp = validator.predict_fill_probability(0.05)
        assert 0.0 <= fp <= 1.0
        ae = validator.predict_adverse_selection(0.05)
        assert isinstance(ae, float)

    def test_from_frozen_calibration_integrity_fail(self):
        data = {
            "schema_version": "v10.forward.frozen.v2",
            "frozen_at": "2026-01-01T00:00:00+00:00",
            "config": {
                "bins": (0.0, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, float("inf")),
                "survival_horizon": 1000.0,
                "spread_capture_bps": 2.0,
                "fee_rebate_bps": 0.5,
                "inventory_cost_bps": 0.2,
                "exit_cost_bps": 0.3,
                "cancellation_cost_bps": 0.05,
                "order_quantity": 0.01,
                "decision_every_n": 10,
                "horizon_ms": 1000,
            },
            "fill_model": {"edges": [], "rates": [], "prior": 0.5},
            "adverse_model": {"edges": [], "rates": []},
            "km_model": {"times": [], "survival": [], "events": [], "at_risk": []},
            "train_summary": {"n_observations": 0, "n_filled": 0, "fill_rate": 0.0},
        }
        artifact = FrozenCalibrationArtifact(data)
        assert not artifact.verify_integrity()
        with pytest.raises(ValueError, match="integrity check"):
            V10ForwardValidator.from_frozen_calibration(artifact)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
