# Next Hypothesis: ACTIVE_FLOW_HEDGE-0.1

## Core Insight from FLOW-SPREAD-0.3 Post-Mortem

FLOW-SPREAD-0.3 failed because:
1. Directional flow measurement had zero weight (no effect)
2. Inventory suppression was too weak (2 bps) to prevent large inventory accumulation
3. No active hedging — only spread widening and adverse selection cancellation

## New Hypothesis

**ACTIVE_FLOW_HEDGE-0.1** proposes a mechanism that:
1. **Uses directional flow for active quoting bias** (non-zero weight)
2. **Implements active inventory hedging** via offsetting trades
3. **Uses stronger, dynamic inventory controls** that scale with inventory level
4. **Combines flow-informed spread adjustment with targeted hedging**

## Mechanism Components

### A. Directional Flow Quoting Bias (replaces directional_flow_weight=0.0)
- `flow_quote_bias_bps`: Base bps adjustment from flow (e.g., 1.0 bps)
- `flow_weight`: 0.5 (significant but not dominant)
- Quote price = mid_price ± (base_spread/2) + flow_bias + inventory_skew

### B. Active Inventory Hedging
- When inventory exceeds threshold, place offsetting trades
- `hedge_threshold_notional`: Start hedging at 20% of max position
- `hedge_ratio`: Hedge 50% of excess inventory immediately
- Hedges use passive orders to minimize adverse selection

### C. Dynamic Inventory Control (replaces static 2 bps penalty)
- `inventory_penalty_base_bps`: 1.0 bps
- `inventory_penalty_slope`: Additional 0.5 bps per 10% of inventory limit
- At 80% inventory limit: penalty = 1.0 + 0.5*8 = 5.0 bps
- At 95% inventory limit: penalty = 1.0 + 0.5*9.5 = 5.75 bps
- Non-linear scaling provides stronger control near limits

### D. Enhanced Risk Parameters
- `max_inventory_breaches_allowed`: 0 (strict)
- `inventory_violation_action`: Reduce quote_size by 50% after 1st breach
- `adverse_selection_threshold_bps`: Tighten to 0.5 (more selective)

## Expected Improvements vs FLOW-SPREAD-0.3

| Mechanism | FLOW-SPREAD-0.3 | ACTIVE_FLOW_HEDGE-0.1 |
|-----------|----------------|------------------------|
| Flow impact on quoting | 0 bps (weight=0) | Active bias (e.g., ±1.0 bps) |
| Inventory control | Linear 2 bps | Non-linear, increases near limits |
| Inventory hedging | None | Active offsetting trades |
| Breach handling | None (just widens) | Quote size reduction after 1st |
| Flow threshold | 0.3 (unitless) | Tuned to flow signal strength |

## Research Plan

1. Create new experiment branch from main (not from frozen FLOW-SPREAD-0.3)
2. Implement ACTIVE_FLOW_HEDGE-0.1 mechanism
3. Retrospective analysis on same 3 OOS captures
4. If promising, forward test on new OOS
5. Maintain NO_DEPLOY until certification

## Key Constraint

Do NOT modify FLOW-SPREAD-0.3 evidence. This is a clean hypothesis on a clean branch.

## First Implementation Target

Config file: `app/mm/config_v21_active_flow_hedge_01bps.json`
Mechanism: Modify `app/mm/quote_engine_v21.py` (new file)
Validation: Run against OOS #1/#2/#3 with same frozen-certification script