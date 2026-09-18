"""Tests for V12 funding rate alignment — no network, synthetic FundingPoints."""
import pytest

from app.v12.funding import (
    FundingPoint,
    get_funding_rate_at,
    average_funding_rate_during,
)

_EIGHT_HOURS_MS = 8 * 3600_000


def _points(specs):
    return [FundingPoint(funding_time=s[0], funding_rate=s[1]) for s in specs]


def test_get_funding_rate_at_returns_most_recent_le_none():
    pts = _points([(100, 0.0001), (1000, 0.0002), (2000, -0.0001)])
    assert get_funding_rate_at(pts, 500) == 0.0001
    assert get_funding_rate_at(pts, 1000) == 0.0002
    assert get_funding_rate_at(pts, 1500) == 0.0002


def test_get_funding_rate_empty_list_returns_zero():
    assert get_funding_rate_at([], 12345) == 0.0


def test_average_funding_full_window_coverage():
    """A single funding point whose 8h window fully covers the hold interval."""
    pts = _points([(0, 0.0002)])
    # hold interval entirely inside the [0, 8h] window
    avg = average_funding_rate_during(pts, start_ms=0, end_ms=8 * 3600_000)
    assert avg == pytest.approx(0.0002)


def test_average_funding_partial_overlap_weighted():
    pts = _points([(0, 0.0002), (8 * 3600_000, 0.0004)])
    # interval spans exactly one full period -> average of the two rates (each 8h/16h)
    avg = average_funding_rate_during(pts, 0, 2 * 8 * 3600_000)
    assert avg == pytest.approx(0.0003)


def test_average_funding_returns_zero_for_no_points():
    assert average_funding_rate_during([], 0, 1000) == 0.0


def test_average_funding_returns_point_rate_for_zero_span():
    pts = _points([(0, 0.0005)])
    assert average_funding_rate_during(pts, 0, 0) == pytest.approx(0.0005)


def test_average_funding_negative_rate_paid_by_short():
    pts = _points([(0, -0.0001)])
    avg = average_funding_rate_during(pts, 0, 8 * 3600_000)
    assert avg == pytest.approx(-0.0001)
