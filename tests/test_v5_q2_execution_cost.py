"""Tests for V5 Q2 contemporaneous execution cost measurement."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.v5_q2_execution_cost import (
    _contemporaneous_gate,
    _maker_gate_from_calibration,
    compare,
    walk_slippage_bps,
)


class TestContemporaneousGate:
    def test_gate_uses_p90_roundtrip(self):
        stats = {
            "effective_roundtrip_taker": {"1000": {"taker_rt_p90_bps": 4.0}},
            "spread": {"p90_bps": 0.5},
        }
        gate = _contemporaneous_gate(stats, notional_usd=1000)
        # gate = rt_p90 + impact + latency + margin
        expected = 4.0 + 0.10 + 0.05 + 0.5
        assert abs(gate["gate_bps"] - expected) < 1e-6

    def test_gate_falls_back_when_no_band(self):
        stats = {"effective_roundtrip_taker": {}, "spread": {"p90_bps": 0.0}}
        gate = _contemporaneous_gate(stats, notional_usd=1000)
        # Should fall back to 3.5 + impact + latency + margin
        expected = 3.5 + 0.10 + 0.05 + 0.5
        assert abs(gate["gate_bps"] - expected) < 1e-6

    def test_gate_includes_spread_p90(self):
        stats = {
            "effective_roundtrip_taker": {"1000": {"taker_rt_p90_bps": 3.0}},
            "spread": {"p90_bps": 1.5},
        }
        gate = _contemporaneous_gate(stats, notional_usd=1000)
        assert gate["spread_p90_bps"] == 1.5

    def test_gate_components_are_present(self):
        stats = {
            "effective_roundtrip_taker": {"1000": {"taker_rt_p90_bps": 3.0}},
            "spread": {"p90_bps": 0.0},
        }
        gate = _contemporaneous_gate(stats, notional_usd=1000)
        assert "taker_roundtrip_p90_bps" in gate
        assert "taker_total_bps" in gate
        assert "gate_bps" in gate
        assert "notional_usd" in gate


class TestMakerGate:
    def test_maker_gate_has_expected_keys(self):
        stats = {
            "maker": {"fee_rt_mean_bps": 2.0, "fee_rt_vip10_bnb_bps": 1.6},
        }
        gate = _maker_gate_from_calibration(stats)
        assert "maker_fee_rt_bps" in gate
        assert "adverse_selection_bps" in gate
        assert "p_fill" in gate
        assert "maker_total_bps" in gate
        assert "gate_bps" in gate

    def test_maker_gate_fee_from_stats(self):
        stats = {
            "maker": {"fee_rt_mean_bps": 2.0, "fee_rt_vip10_bnb_bps": 1.6},
        }
        gate = _maker_gate_from_calibration(stats)
        assert gate["maker_fee_rt_bps"] == 2.0


class TestCompare:
    def test_compare_returns_required_keys(self):
        cont_gate = {"gate_bps": 5.0, "taker_total_bps": 4.5}
        maker_gate = {"gate_bps": 3.0}
        result = compare(cont_gate, maker_gate)
        assert "gate_difference_bps" in result
        assert "gate_verdict" in result
        assert "signal_viability" in result
        assert "taker_net_at_low_signal_bps" in result
        assert "taker_net_at_high_signal_bps" in result

    def test_compare_detects_higher_contemporary_cost(self):
        cont_gate = {"gate_bps": 6.0, "taker_total_bps": 5.5}
        maker_gate = {"gate_bps": 3.0}
        result = compare(cont_gate, maker_gate)
        assert result["gate_verdict"] == "CONTEMPORANEOUS_COST_HIGHER"
        assert result["gate_difference_bps"] > 0.5

    def test_compare_detects_lower_contemporary_cost(self):
        cont_gate = {"gate_bps": 3.0, "taker_total_bps": 2.5}
        maker_gate = {"gate_bps": 2.0}
        result = compare(cont_gate, maker_gate)
        assert result["gate_verdict"] == "CONTEMPORANEOUS_COST_LOWER"
        assert result["gate_difference_bps"] < -0.5

    def test_compare_detects_similar_cost(self):
        cont_gate = {"gate_bps": 4.7, "taker_total_bps": 4.2}
        maker_gate = {"gate_bps": 3.0}
        result = compare(cont_gate, maker_gate)
        assert result["gate_verdict"] == "CONTEMPORANEOUS_COST_SIMILAR"

    def test_compare_viability_fail_when_net_negative(self):
        cont_gate = {"gate_bps": 5.0, "taker_total_bps": 4.5}
        maker_gate = {"gate_bps": 5.0}
        result = compare(cont_gate, maker_gate)
        assert "FAIL" in result["signal_viability"]

    def test_compare_cost_to_signal_ratio(self):
        cont_gate = {"gate_bps": 4.6658, "taker_total_bps": 4.1658}
        maker_gate = {"gate_bps": 3.0}
        result = compare(cont_gate, maker_gate)
        # 4.6658 / 0.0685 ≈ 68.1
        assert result["cost_to_signal_ratio_low"] > 60
        assert result["cost_to_signal_ratio_high"] > 50


class TestQ2WalkSlippage:
    def test_walk_slippage_no_crossing(self):
        mid = 50000.0
        asks = [(50000.1, 10.0)]
        slip = walk_slippage_bps(asks, mid, 1000)
        assert slip is not None
        assert 0.01 < slip < 0.03

    def test_walk_slippage_crosses_levels(self):
        mid = 100.0
        asks = [(100.1, 0.5), (100.2, 0.5), (100.3, 0.5)]
        slip = walk_slippage_bps(asks, mid, 100)
        assert slip is not None and slip > 0.1

    def test_walk_slippage_insufficient_depth(self):
        mid = 100.0
        asks = [(100.1, 0.1)]
        assert walk_slippage_bps(asks, mid, 1000) is None

    def test_walk_slippage_empty(self):
        assert walk_slippage_bps([], 100.0, 100) is None


class TestQ2ReportBuild:
    def test_build_report_creates_json_and_md(self, tmp_path):
        stats = {
            "n_samples": 10,
            "window_seconds": 10.0,
            "spread": {"p90_bps": 1.0, "mean_bps": 0.8, "median_bps": 0.7},
            "effective_roundtrip_taker": {
                "1000": {"taker_rt_p90_bps": 3.5, "taker_rt_median_bps": 3.0}
            },
            "maker": {"fee_rt_mean_bps": 2.0, "fee_rt_vip10_bnb_bps": 1.6},
        }
        sample_path = tmp_path / "cost_sampler_test.jsonl"
        sample_path.write_text("")
        report = __import__("app.v5_q2_execution_cost", fromlist=["build_report"]).build_report(
            sample_path, stats, tmp_path)
        assert (tmp_path / "v5_q2_report.json").exists()
        assert (tmp_path / "v5_q2_report.md").exists()
        assert "gate_bps" in report["contemporaneous_cost"]
        assert "comparison" in report

    def test_build_report_contains_governance(self, tmp_path):
        stats = {
            "n_samples": 5,
            "window_seconds": 5.0,
            "spread": {"p90_bps": 1.0},
            "effective_roundtrip_taker": {"1000": {"taker_rt_p90_bps": 3.0}},
            "maker": {"fee_rt_mean_bps": 2.0},
        }
        sample_path = tmp_path / "cost_sampler_test.jsonl"
        sample_path.write_text("")
        report = __import__("app.v5_q2_execution_cost", fromlist=["build_report"]).build_report(
            sample_path, stats, tmp_path)
        assert report["governance"]["ORDERFLOW_BASELINE_V5_NO_LIVE_TRADE"] is True
