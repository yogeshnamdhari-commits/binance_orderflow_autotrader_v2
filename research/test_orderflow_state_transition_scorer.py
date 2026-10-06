#!/usr/bin/env python3
"""Synthetic tests for the frozen OFST A-002 scorer."""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

from score_orderflow_state_transition import (
    BOOTSTRAP_SEED,
    OFI_WINDOW_MS,
    SAFETY_BUFFER_BPS,
    Z_WINDOW_MS,
    directional_return_bps,
    level_ofi,
    rolling_sum_at,
    robust_z,
    state_direction,
    vwap_for_notional,
    vwap_for_quantity,
)


def test_long_short_signs() -> None:
    assert directional_return_bps("LONG", 100.0, 101.0) > 0
    assert directional_return_bps("SHORT", 100.0, 101.0) < 0
    assert directional_return_bps("LONG", 101.0, 100.0) < 0
    assert directional_return_bps("SHORT", 101.0, 100.0) > 0


def test_vwap_same_base_quantity() -> None:
    entry, qty = vwap_for_notional(((100.0, 2.0),), 100.0)
    exit_, qty2 = vwap_for_quantity(((101.0, 0.5), (102.0, 2.0)), qty)
    assert abs(entry - 100.0) < 1e-12
    assert abs(qty - 1.0) < 1e-12
    assert abs(exit_ - 101.5) < 1e-12
    assert abs(qty2 - qty) < 1e-12


def test_multi_level_ofi_matches_repository_definition() -> None:
    prev_bids = ((100.0, 1.0), (99.0, 2.0))
    prev_asks = ((101.0, 1.0), (102.0, 2.0))
    curr_bids = ((100.0, 2.0), (98.0, 2.0))
    curr_asks = ((101.0, 0.5), (103.0, 2.0))
    got = level_ofi(prev_bids, prev_asks, curr_bids, curr_asks)
    assert abs(got[0] - 1.5) < 1e-12
    assert isinstance(got[1], float)


def test_registered_rolling_500ms_ofi_window() -> None:
    observations = [
        (400, 1.0),
        (500, 2.0),
        (900, 4.0),
        (901, 8.0),
    ]
    # Inclusive window [t-500ms, t].
    assert abs(rolling_sum_at(observations, 499, 500) - 1.0) < 1e-12
    assert abs(rolling_sum_at(observations, 500, 500) - 3.0) < 1e-12
    assert abs(rolling_sum_at(observations, 900, 500) - 7.0) < 1e-12
    assert abs(rolling_sum_at(observations, 901, 500) - 14.0) < 1e-12


def test_ofi_window_boundary_inclusive_current_event() -> None:
    # t-500 included, t-501 excluded, t included.
    observations = [
        (0, 1.0),
        (498, 1.0),
        (500, 2.0),
        (998, 3.0),
        (999, 4.0),
    ]
    # At t=999: [499, 999] -> t=500, 998, 999 -> 2+3+4 = 9
    assert abs(rolling_sum_at(observations, 999, OFI_WINDOW_MS) - 9.0) < 1e-12
    # At t=998: [498, 998] -> t=498, 500, 998 -> 1+2+3 = 6
    assert abs(rolling_sum_at(observations, 998, OFI_WINDOW_MS) - 6.0) < 1e-12


def test_60s_normalization_excludes_current_event() -> None:
    observations = [(0, 1.0), (60000, 1.0), (120000, 1.0)]
    prior = [v for ts, v in observations if ts < 120000]
    assert len(prior) == 2 and prior == [1.0, 1.0]
    z = robust_z(1.0, sorted(prior))
    assert z is None


def test_exactly_60s_boundary_in_normalization() -> None:
    observations = [(0, 1.0), (Z_WINDOW_MS, 1.0), (2 * Z_WINDOW_MS, 2.0)]
    # History for t=2*Z_WINDOW_MS is [t-Z_WINDOW_MS, t) = [Z_WINDOW_MS, 2*Z_WINDOW_MS)
    prior = [v for ts, v in observations if Z_WINDOW_MS <= ts < 2 * Z_WINDOW_MS]
    assert len(prior) == 1 and prior == [1.0]
    z = robust_z(2.0, sorted(prior))
    assert z is None


def test_mad_zero_fails_closed() -> None:
    assert robust_z(2.0, [1.0, 1.0, 3.0]) is None


def test_nonzero_mad_produces_zscore() -> None:
    z = robust_z(3.0, [1.0, 2.0, 3.0])
    assert z is not None
    assert math.isfinite(z)
    assert abs(z - 1.0 / 1.4826) < 1e-6


def test_single_value_window_fails_closed() -> None:
    assert robust_z(5.0, [5.0]) is None


def test_two_identical_values_fails_closed() -> None:
    assert robust_z(3.0, [3.0, 3.0]) is None


def test_empty_window_fails_closed() -> None:
    assert robust_z(1.0, []) is None


def test_ofi_1_and_ofi_5_independently_normalized() -> None:
    z5 = robust_z(3.0, sorted([3.0, 3.0, 3.0]))
    assert z5 is None
    z1 = robust_z(3.0, sorted([1.0, 2.0, 4.0]))  # median=2.0, deviations=[1,0,2], MAD=1
    assert z1 is not None


def test_ofi_1_and_ofi_5_not_state_when_only_two_extreme() -> None:
    z1 = robust_z(2.0, [0.0, 0.0])
    z5 = robust_z(2.0, [0.0, 0.0])
    z10 = robust_z(0.0, [0.0, 0.0])
    assert state_direction((z1, z5, z10), 0.80) is None

    prior = sorted([-0.8, -0.4, 0.0, 0.4, 0.8])
    z1 = robust_z(3.0, prior)
    z5 = robust_z(3.0, prior)
    z10 = robust_z(0.5, prior)
    assert z1 is not None and z5 is not None and z10 is not None
    assert state_direction((z1, z5, z10), 0.80) is None


def test_all_aligned_flow_triggers_state() -> None:
    prior = sorted([-0.6, -0.3, 0.0, 0.3, 0.6])
    z1 = robust_z(2.0, prior)
    z5 = robust_z(2.0, prior)
    z10 = robust_z(2.0, prior)
    assert z1 is not None and z5 is not None and z10 is not None
    assert state_direction((z1, z5, z10), 0.70) == "LONG"
    assert state_direction((z1, z5, z10), -0.70) is None


def test_negative_direction_symmetry() -> None:
    prior = sorted([-0.6, -0.3, 0.0, 0.3, 0.6])
    z1 = robust_z(-2.0, prior)
    z5 = robust_z(-2.0, prior)
    z10 = robust_z(-2.0, prior)
    assert z1 is not None and z5 is not None and z10 is not None
    assert state_direction((z1, z5, z10), -0.70) == "SHORT"


def test_registered_constants() -> None:
    assert BOOTSTRAP_SEED == 20261003
    assert SAFETY_BUFFER_BPS == 2.0


def test_temp_workspace_available() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        assert Path(tmp).exists()


if __name__ == "__main__":
    tests = [
        test_long_short_signs,
        test_vwap_same_base_quantity,
        test_multi_level_ofi_matches_repository_definition,
        test_registered_rolling_500ms_ofi_window,
        test_ofi_window_boundary_inclusive_current_event,
        test_60s_normalization_excludes_current_event,
        test_exactly_60s_boundary_in_normalization,
        test_mad_zero_fails_closed,
        test_nonzero_mad_produces_zscore,
        test_single_value_window_fails_closed,
        test_two_identical_values_fails_closed,
        test_empty_window_fails_closed,
        test_ofi_1_and_ofi_5_independently_normalized,
        test_ofi_1_and_ofi_5_not_state_when_only_two_extreme,
        test_all_aligned_flow_triggers_state,
        test_negative_direction_symmetry,
        test_registered_constants,
        test_temp_workspace_available,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print("PASS OFST scorer synthetic audit")
