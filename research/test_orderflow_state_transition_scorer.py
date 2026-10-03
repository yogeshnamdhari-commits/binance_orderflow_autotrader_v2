#!/usr/bin/env python3
"""Synthetic tests for the frozen OFST A-002 scorer."""

from __future__ import annotations

import tempfile
from pathlib import Path

from score_orderflow_state_transition import (
    BOOTSTRAP_SEED,
    SAFETY_BUFFER_BPS,
    directional_return_bps,
    level_ofi,
    rolling_sum_at,
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

    # L1: bid +1, ask -0.5 => +1.5.
    assert abs(got[0] - 1.5) < 1e-12
    assert isinstance(got[1], float)


def test_registered_rolling_500ms_ofi_window() -> None:
    observations = [
        (400, 1.0),
        (500, 2.0),
        (900, 4.0),
        (901, 8.0),
    ]
    assert abs(rolling_sum_at(observations, 900, 500) - 7.0) < 1e-12
    assert abs(rolling_sum_at(observations, 901, 500) - 12.0) < 1e-12


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
        test_registered_constants,
        test_temp_workspace_available,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print("PASS OFST scorer synthetic audit")
