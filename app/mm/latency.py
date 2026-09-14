from __future__ import annotations

from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class LatencyModel:
    """Model WebSocket + processing latency."""

    mean_latency_ms: float = 100.0
    std_latency_ms: float = 30.0

    def sample_latency(self) -> float:
        """Sample realistic latency with jitter."""
        latency = np.random.normal(self.mean_latency_ms, self.std_latency_ms)
        return max(10.0, min(500.0, latency))


def check_quote_staleness(
    quote_price: float,
    mid_price_at_fill_time: float,
    current_spread_bps: float,
    max_drift_std_devs: float = 1.0,
) -> bool:
    """
    Check if quote is stale.
    """

    price_drift_bps = abs(mid_price_at_fill_time - quote_price) * 10_000.0 / quote_price
    max_acceptable_drift = current_spread_bps * max_drift_std_devs

    return price_drift_bps > max_acceptable_drift
