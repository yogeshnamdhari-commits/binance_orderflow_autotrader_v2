"""V16 queue-pressure proxy.

Since the data does not contain individual order IDs, we estimate queue
pressure from observable depth changes, trades, and cancellations.

Definition:
  queue_pressure = (adds_at_touch - cancels_at_touch) / (adds_at_touch + cancels_at_touch + eps)

Where:
  - adds_at_touch: quantity added to the best bid/ask level in the lookback window
  - cancels_at_touch: quantity removed from the best bid/ask level in the lookback window

Economic interpretation:
  - High positive queue_pressure: more orders being added than canceled at the touch
    → new orders are behind existing queue → our order would be filled after existing ones
  - High negative queue_pressure: more cancellations than additions → queue thinning
    → our order would be filled sooner

Limitations:
  - Does not account for order sizes (a single large order could dominate)
  - Does not account for hidden liquidity
  - Does not account for cross-venue queue dynamics
  - Does not account for order priority rules (time precedence only)
"""
from __future__ import annotations

import numpy as np
import pandas as pd


class V16QueuePressure:
    def __init__(self, window_ms: int = 10000):
        self._window_ms = window_ms

    def compute(self, books: list, trades: list) -> pd.DataFrame:
        rows = []
        trade_idx = 0
        n_trades = len(trades)

        for i, bk in enumerate(books):
            while trade_idx < n_trades and trades[trade_idx].ts_ms <= bk.ts_ms:
                trade_idx += 1

            window_start = bk.ts_ms - self._window_ms
            w_trades = [t for t in trades[:trade_idx] if t.ts_ms >= window_start]

            adds = bk.adds if hasattr(bk, 'adds') and bk.adds else 0.0
            cancels = bk.cancels if hasattr(bk, 'cancels') and bk.cancels else 0.0
            net = adds - cancels
            tot = adds + cancels + 1e-9
            queue_pressure = net / tot

            rows.append({
                "ts_ms": bk.ts_ms,
                "adds_at_touch": adds,
                "cancels_at_touch": cancels,
                "net_flow_at_touch": net,
                "queue_pressure": queue_pressure,
            })

        return pd.DataFrame(rows)
