#!/usr/bin/env python3
"""Deterministic pre-capture audit for ORDERFLOW_STATE_TRANSITION-0.1 A-002.

Code/measurement audit only. Synthetic books only; no research captures or
external market data are consumed.
"""

from __future__ import annotations

from math import isclose


TAKER_FEE_RATE = 0.0005
SAFETY_BUFFER_BPS = 2.0
INITIAL_NOTIONAL_USDT = 100.0


def vwap_for_notional(
    levels: list[tuple[float, float]],
    notional_usdt: float,
) -> tuple[float, float]:
    """Return VWAP and base quantity for a quoted-notional purchase/sale."""
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
            return spent / base_qty, base_qty

    raise ValueError("insufficient displayed depth")


def vwap_for_quantity(
    levels: list[tuple[float, float]],
    base_qty_target: float,
) -> tuple[float, float]:
    """Return VWAP and filled base quantity for a fixed base quantity."""
    if not levels or base_qty_target <= 0:
        raise ValueError("invalid input")

    remaining = base_qty_target
    base_qty = 0.0
    notional = 0.0

    for price, qty in levels:
        if price <= 0 or qty <= 0:
            continue
        take_qty = min(remaining, qty)
        notional += take_qty * price
        base_qty += take_qty
        remaining -= take_qty
        if remaining <= 1e-12:
            return notional / base_qty, base_qty

    raise ValueError("insufficient displayed depth")


def executable_gross_bps(side: str, entry_vwap: float, exit_vwap: float) -> float:
    if side == "LONG":
        return (exit_vwap / entry_vwap - 1.0) * 10_000.0
    if side == "SHORT":
        return (entry_vwap / exit_vwap - 1.0) * 10_000.0
    raise ValueError("side must be LONG or SHORT")


def exact_taker_fee_bps(initial_notional: float, entry_notional: float, exit_notional: float) -> float:
    fee_usdt = TAKER_FEE_RATE * (entry_notional + exit_notional)
    return fee_usdt / initial_notional * 10_000.0


def net_bps(executable_gross: float, fee_bps: float, funding_bps: float = 0.0) -> float:
    return executable_gross - fee_bps - funding_bps - SAFETY_BUFFER_BPS


def test_long_fixed_quantity_vwap_and_cost_stack() -> None:
    entry_vwap, entry_qty = vwap_for_notional(
        [(100.0, 2.0), (101.0, 2.0)],
        INITIAL_NOTIONAL_USDT,
    )
    exit_vwap, exit_qty = vwap_for_quantity(
        [(101.0, 0.5), (102.0, 2.0)],
        entry_qty,
    )

    assert isclose(entry_vwap, 100.0, rel_tol=0, abs_tol=1e-12)
    assert isclose(entry_qty, 1.0, rel_tol=0, abs_tol=1e-12)
    assert isclose(exit_vwap, 101.5, rel_tol=0, abs_tol=1e-12)
    assert isclose(exit_qty, 1.0, rel_tol=0, abs_tol=1e-12)

    entry_notional = entry_vwap * entry_qty
    exit_notional = exit_vwap * exit_qty
    gross = executable_gross_bps("LONG", entry_vwap, exit_vwap)
    fees = exact_taker_fee_bps(INITIAL_NOTIONAL_USDT, entry_notional, exit_notional)

    assert isclose(gross, 150.0, rel_tol=0, abs_tol=1e-9)
    assert isclose(fees, 10.075, rel_tol=0, abs_tol=1e-9)
    assert isclose(net_bps(gross, fees), 137.925, rel_tol=0, abs_tol=1e-9)


def test_short_directional_symmetry() -> None:
    entry_vwap, entry_qty = vwap_for_notional(
        [(100.0, 2.0), (99.0, 2.0)],
        INITIAL_NOTIONAL_USDT,
    )
    exit_vwap, exit_qty = vwap_for_quantity(
        [(99.0, 2.0)],
        entry_qty,
    )

    assert isclose(entry_vwap, 100.0, rel_tol=0, abs_tol=1e-12)
    assert isclose(entry_qty, 1.0, rel_tol=0, abs_tol=1e-12)
    assert isclose(exit_vwap, 99.0, rel_tol=0, abs_tol=1e-12)
    assert isclose(exit_qty, 1.0, rel_tol=0, abs_tol=1e-12)

    gross = executable_gross_bps("SHORT", entry_vwap, exit_vwap)
    fees = exact_taker_fee_bps(INITIAL_NOTIONAL_USDT, 100.0, 99.0)

    assert isclose(gross, 101.01010101010101, rel_tol=0, abs_tol=1e-9)
    assert isclose(fees, 9.95, rel_tol=0, abs_tol=1e-9)
    assert isclose(net_bps(gross, fees), 89.06010101010101, rel_tol=0, abs_tol=1e-9)


def test_funding_is_separate_cost_component() -> None:
    assert isclose(net_bps(20.0, 10.0, funding_bps=0.0), 8.0, rel_tol=0, abs_tol=1e-9)
    assert isclose(net_bps(20.0, 10.0, funding_bps=1.5), 6.5, rel_tol=0, abs_tol=1e-9)


def test_insufficient_depth_is_fail_closed() -> None:
    try:
        vwap_for_notional([(100.0, 0.5)], INITIAL_NOTIONAL_USDT)
    except ValueError as exc:
        assert "insufficient displayed depth" in str(exc)
    else:
        raise AssertionError("insufficient displayed depth must fail closed")


if __name__ == "__main__":
    tests = [
        test_long_fixed_quantity_vwap_and_cost_stack,
        test_short_directional_symmetry,
        test_funding_is_separate_cost_component,
        test_insufficient_depth_is_fail_closed,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print("PASS synthetic economic-measurement audit")
