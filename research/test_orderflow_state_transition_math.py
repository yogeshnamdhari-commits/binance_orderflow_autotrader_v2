#!/usr/bin/env python3
"""Deterministic pre-capture audit for ORDERFLOW_STATE_TRANSITION-0.1 A-002.

This is a code/measurement audit only. It uses synthetic books and does not
consume research captures or external market data.
"""

from __future__ import annotations

from math import isclose


FEE_BPS = 10.0
SAFETY_BUFFER_BPS = 2.0
NOTIONAL_USDT = 100.0


def notional_vwap(levels: list[tuple[float, float]], notional_usdt: float) -> float:
    """Consume displayed price/quantity levels until the requested USDT notional."""
    if not levels or notional_usdt <= 0:
        raise ValueError("invalid input")

    remaining = notional_usdt
    base_qty = 0.0
    spent = 0.0

    for price, qty in levels:
        if price <= 0 or qty <= 0:
            continue
        level_notional = price * qty
        take_notional = min(remaining, level_notional)
        take_qty = take_notional / price
        spent += take_qty * price
        base_qty += take_qty
        remaining -= take_notional
        if remaining <= 1e-12:
            return spent / base_qty

    raise ValueError("insufficient displayed depth")


def executable_gross_bps(
    side: str,
    entry_vwap: float,
    exit_vwap: float,
) -> float:
    if side == "LONG":
        return (exit_vwap / entry_vwap - 1.0) * 10_000.0
    if side == "SHORT":
        return (entry_vwap / exit_vwap - 1.0) * 10_000.0
    raise ValueError("side must be LONG or SHORT")


def net_bps(
    executable_gross: float,
    funding_bps: float = 0.0,
) -> float:
    return executable_gross - FEE_BPS - funding_bps - SAFETY_BUFFER_BPS


def test_long_vwap_and_net() -> None:
    # Exactly 100 USDT can be filled at the top ask.
    entry = notional_vwap([(100.0, 2.0), (101.0, 2.0)], NOTIONAL_USDT)
    # Exit requires two levels and therefore has measurable depth impact.
    exit_ = notional_vwap([(101.0, 0.5), (102.0, 2.0)], NOTIONAL_USDT)

    assert isclose(entry, 100.0, rel_tol=0, abs_tol=1e-12)
    # 50 USDT at 101 + 50 USDT at 102 => VWAP 101.5.
    assert isclose(exit_, 101.5, rel_tol=0, abs_tol=1e-12)

    gross = executable_gross_bps("LONG", entry, exit_)
    assert isclose(gross, 150.0, rel_tol=0, abs_tol=1e-9)

    # 150 gross - 10 fees - 2 safety = 138 bps net when funding is zero.
    assert isclose(net_bps(gross), 138.0, rel_tol=0, abs_tol=1e-9)


def test_short_symmetry() -> None:
    entry = notional_vwap([(100.0, 2.0), (99.0, 2.0)], NOTIONAL_USDT)
    exit_ = notional_vwap([(99.0, 0.5), (98.0, 2.0)], NOTIONAL_USDT)

    assert isclose(entry, 100.0, rel_tol=0, abs_tol=1e-12)
    assert isclose(exit_, 99.0, rel_tol=0, abs_tol=1e-12)

    gross = executable_gross_bps("SHORT", entry, exit_)
    assert isclose(gross, 100.0, rel_tol=0, abs_tol=1e-9)
    assert isclose(net_bps(gross), 88.0, rel_tol=0, abs_tol=1e-9)


def test_funding_is_separate_cost_component() -> None:
    gross = 20.0
    assert isclose(net_bps(gross, funding_bps=0.0), 8.0, rel_tol=0, abs_tol=1e-9)
    assert isclose(net_bps(gross, funding_bps=1.5), 6.5, rel_tol=0, abs_tol=1e-9)


def test_insufficient_depth_is_fail_closed() -> None:
    try:
        notional_vwap([(100.0, 0.5)], NOTIONAL_USDT)
    except ValueError as exc:
        assert "insufficient displayed depth" in str(exc)
    else:
        raise AssertionError("insufficient displayed depth must fail closed")


if __name__ == "__main__":
    tests = [
        test_long_vwap_and_net,
        test_short_symmetry,
        test_funding_is_separate_cost_component,
        test_insufficient_depth_is_fail_closed,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print("PASS synthetic economic-measurement audit")
