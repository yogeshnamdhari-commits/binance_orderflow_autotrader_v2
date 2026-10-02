#!/usr/bin/env python3
"""Deterministic pre-capture audit for ORDERFLOW_STATE_TRANSITION-0.1 A-002.

Code/measurement audit only. Synthetic books/timestamps only; no research
captures, account access, or external market data are consumed.

The audit checks:
- notional-based entry VWAP
- fixed-base-quantity exit VWAP
- LONG/SHORT sign symmetry on the same price path
- exact taker fee normalization from both legs
- fixed 2.0 bps safety buffer
- funding as a separate cost component
- fail-closed insufficient depth
- deterministic signal/entry/exit timestamp bookkeeping
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
    """Return VWAP and base quantity after consuming quoted notional."""
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


def exact_taker_fee_bps(
    initial_notional: float,
    entry_notional: float,
    exit_notional: float,
) -> float:
    """Normalize actual two-leg fees by initial entry notional."""
    if initial_notional <= 0 or entry_notional <= 0 or exit_notional <= 0:
        raise ValueError("invalid notional")
    fee_usdt = TAKER_FEE_RATE * (entry_notional + exit_notional)
    return fee_usdt / initial_notional * 10_000.0


def net_bps(
    executable_gross: float,
    fee_bps: float,
    funding_bps: float = 0.0,
) -> float:
    """Safety buffer is intentionally fixed, not a driftable parameter."""
    return executable_gross - fee_bps - funding_bps - SAFETY_BUFFER_BPS


def score_timestamp_fields(
    signal_time_exchange_ms: int,
    signal_book_time_exchange_ms: int,
    entry_book_time_exchange_ms: int,
    exit_book_time_exchange_ms: int,
    target_exit_time_exchange_ms: int,
) -> dict[str, int]:
    """Build deterministic timestamp diagnostics for a scored signal."""
    if not (
        signal_book_time_exchange_ms <= signal_time_exchange_ms
        <= entry_book_time_exchange_ms <= exit_book_time_exchange_ms
    ):
        raise ValueError("non-monotonic signal/book/entry/exit timestamps")
    return {
        "signal_time_exchange_ms": signal_time_exchange_ms,
        "book_snapshot_age_ms": signal_time_exchange_ms - signal_book_time_exchange_ms,
        "entry_snapshot_delay_ms": entry_book_time_exchange_ms - signal_time_exchange_ms,
        "exit_snapshot_delay_ms": exit_book_time_exchange_ms - signal_time_exchange_ms,
        "exit_resolution_error_ms": exit_book_time_exchange_ms - target_exit_time_exchange_ms,
    }


def test_long_and_short_sign_symmetry() -> None:
    # The same entry/exit prices must produce opposite directional signs.
    # Exact equal magnitude is not expected for simple-return bps because
    # LONG and SHORT use reciprocal price ratios.
    long_gross = executable_gross_bps("LONG", 100.0, 101.0)
    short_gross = executable_gross_bps("SHORT", 100.0, 101.0)

    assert long_gross > 0
    assert short_gross < 0
    assert isclose(long_gross, 100.0, rel_tol=0, abs_tol=1e-12)
    assert isclose(short_gross, -99.00990099009901, rel_tol=0, abs_tol=1e-12)

    # Reversing the underlying price path reverses both directional signs.
    long_loss = executable_gross_bps("LONG", 101.0, 100.0)
    short_gain = executable_gross_bps("SHORT", 101.0, 100.0)

    assert long_loss < 0
    assert short_gain > 0

def test_long_fixed_quantity_vwap_and_exact_fee_normalization() -> None:
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
    fees = exact_taker_fee_bps(
        INITIAL_NOTIONAL_USDT,
        entry_notional,
        exit_notional,
    )

    assert isclose(gross, 150.0, rel_tol=0, abs_tol=1e-9)
    # 5 bps * (100 + 101.5) / 100 = 10.075 bps.
    assert isclose(fees, 10.075, rel_tol=0, abs_tol=1e-9)
    assert isclose(
        net_bps(gross, fees),
        137.925,
        rel_tol=0,
        abs_tol=1e-9,
    )


def test_funding_is_separate_cost_component() -> None:
    assert isclose(
        net_bps(20.0, 10.0, funding_bps=0.0),
        8.0,
        rel_tol=0,
        abs_tol=1e-9,
    )
    assert isclose(
        net_bps(20.0, 10.0, funding_bps=1.5),
        6.5,
        rel_tol=0,
        abs_tol=1e-9,
    )


def test_insufficient_depth_is_fail_closed() -> None:
    try:
        vwap_for_notional([(100.0, 0.5)], INITIAL_NOTIONAL_USDT)
    except ValueError as exc:
        assert "insufficient displayed depth" in str(exc)
    else:
        raise AssertionError("insufficient displayed depth must fail closed")


def test_timestamp_discipline_and_freshness_fields() -> None:
    fields = score_timestamp_fields(
        signal_time_exchange_ms=1_000,
        signal_book_time_exchange_ms=1_000,
        entry_book_time_exchange_ms=1_080,
        exit_book_time_exchange_ms=6_020,
        target_exit_time_exchange_ms=6_000,
    )

    assert fields["signal_time_exchange_ms"] == 1_000
    # Signal is generated from the current reconstructed depth event, so its
    # signal-time book age is exactly zero in the registered reconstruction.
    assert fields["book_snapshot_age_ms"] == 0
    assert fields["entry_snapshot_delay_ms"] == 80
    assert fields["exit_snapshot_delay_ms"] == 5_020
    assert fields["exit_resolution_error_ms"] == 20


if __name__ == "__main__":
    tests = [
        test_long_and_short_sign_symmetry,
        test_long_fixed_quantity_vwap_and_exact_fee_normalization,
        test_funding_is_separate_cost_component,
        test_insufficient_depth_is_fail_closed,
        test_timestamp_discipline_and_freshness_fields,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print("PASS synthetic economic-measurement audit")
