# ACTIVE_FLOW_HEDGE-0.1 Implementation with Performance Fix

This file contains the complete implementation changes needed for the
ACTIVE_FLOW_HEDGE-0.1 mechanism. These changes are to be applied with the
frozen specification in NEXT_HYPOTHESIS.md.

## Performance Fix (Mandatory)

The _future_mid_by_time function uses O(N) scanning per query. With ~35k depth
events and hundreds of fills, this becomes O(N^2). Replace with prefix sums:

```python
# Add at top of run_event_backtest():
from bisect import bisect_right

# After mids list is populated:
mid_times = [ts for ts, _ in mids]
mid_prefix = [0.0]
for _, mid in mids:
    mid_prefix.append(mid_prefix[-1] + mid)

def future_mid_fast(fill_ts: int, horizon_ns: int) -> float | None:
    left = bisect_right(mid_times, fill_ts)
    right = bisect_right(mid_times, fill_ts + horizon_ns)
    if right <= left:
        return None
    return (mid_prefix[right] - mid_prefix[left]) / (right - left)
```

## ACTIVE_FLOW_HEDGE-0.1 Changes

### 1. Config file
New config: app/mm/config_v21_active_flow_hedge_01bps.json

### 2. event_backtest.py modifications

a. Add new fields to EventBacktestResult dataclass
b. Add flow_bias tracking in the loop
c. Replace the expensive AS calculation with bisect
d. Return new metrics

### 3. backtest.py modifications

Update generate_quotes() to accept new parameters:
- inventory_penalty_bps override
- flow_imbalance
- flow_quote_bias_bps
- quote_size_scale

## Gate Definitions (UNCHANGED from spec)

All 7 gates use the same definitions whether testing FLOW-SPREAD-0.3 or
ACTIVE_FLOW_HEDGE-0.1:
- realized_pnl_positive: realized_pnl_usd > 0
- net_pnl_positive: net_pnl_usd > 0  
- inventory_within_limit: inventory_max <= max_position_notional_usd
- no_inventory_breaches: inventory_limit_breaches == 0
- sufficient_fills: fills >= 100
- gross_capture_positive: gross_spread_capture_usd > 0
- attribution_reconciled: |residual| <= 1e-6