# FLOW-SPREAD-0.3 Post-Mortem: Failure Mechanism Analysis

## Context
- Frozen candidate: commit 5d0d762 (config sha256 6d43d31d)
- Direction: 3 untouched OOS captures, 2/3 negative realized P&L, OOS #3 violates inventory gate
- Live status: NO_DEPLOY

## Evidence Summary

| OOS | Period (IST) | Realized PnL | Net PnL | Inventory Carry | Max Inv | Breaches | Gates |
|-----|-------------|-------------|---------|-----------------|---------|----------|-------|
| #1 | Sep 25 22:45-23:45 | +$1,888.33 | -$6.53 | +$1,892.22 | $1,895 | 0 | 6/7 |
| #2 | Sep 26 01:54-02:54 | -$1,075.19 | -$3.69 | -$1,072.53 | $1,486 | 0 | 5/7 |
| #3 | Sep 27 19:23-20:23 | -$3,329.51 | -$16.25 | -$3,324.66 | $4,997 | 27 | 4/7 |

Aggregate: 1,351 fills, -$1,516.37 realized PnL, -$26.47 net PnL

## Root Cause: Mechanism Failure, Not Parameter Failure

### 1. Directional flow has zero weight (directional_flow_weight: 0.0)

The config comment claims "flow-adjusted spread (0.3 bps per unit flow)" but
`directional_flow_weight` is 0.0. The flow measurement is enabled but has NO
effect on quoting. The strategy cannot express any directional bias, even when
flow is strongly one-sided.

Impact: The strategy quotes symmetrically regardless of flow direction, missing
the core mechanism FLOW-SPREAD-0.3 was designed to exploit.

### 2. Inventory suppression is too weak (2 bps penalty)

`inventory_penalty_bps: 2.0` means the spread widens by 2 bps per unit of
inventory. Against BTCUSDT volatility, this is negligible. In OOS #3, inventory
grew to $4,997 (near the $5,000 cap) with 27 breaches. The 2 bps penalty was
insufficient to reduce quoting aggressiveness enough to control inventory.

### 3. No active inventory hedging

The strategy only widens spreads and cancels on adverse selection. It does NOT
hedge inventory risk through offsetting trades. When inventory builds up in one
direction, the strategy is exposed to MTM risk that can outweigh realized gains.

## Failure Pattern by Capture

### OOS #1 (positive realized, failed net PnL)
- Inventory happened to move in the strategy's favor (short inventory, rising mid)
- Positive realized PnL of $1,888 was entirely inventory carry, not spread capture
- Terminal MTM wiped out the realized gain (net -$6.53)
- Failure type: ENDPOINT_ARTIFACT — realized success but net loss

### OOS #2 (negative realized, failed realized PnL)
- Inventory moved against the strategy (long inventory, falling mid)
- Negative realized PnL of -$1,075 from carry and adverse selection
- No inventory breaches, but negative realized is fatal
- Failure type: PERSISTENT_CARRY — negative realized throughout

### OOS #3 (negative realized + inventory breach)
- Large inventory accumulation ($4,997, near cap) with 27 limit breaches
- Strongly negative realized PnL of -$3,329
- Inventory suppression failed to prevent accumulation
- Failure type: PERSISTENT_CARRY + INVENTORY_BREACH

## Why the Pattern Is Consistent

All three captures show the same mechanism:
1. Inventory builds up (no active hedging)
2. Market moves against inventory direction (no directional bias protection)
3. Weak 2 bps penalty doesn't reduce quoting enough to stop inventory growth
4. Result depends on market direction at endpoint, not strategy skill

The 0.3 bps flow adjustment (which has zero weight) is irrelevant because the
directional flow signal has no effect on quoting. The strategy is a symmetric
market maker with weak inventory suppression.

## Conclusion

FLOW-SPREAD-0.3 does not have a parameter problem — it has a mechanism problem.
The directional flow feature is disabled (weight=0) and the inventory suppression
is too weak to control risk. No amount of retuning within the frozen experiment
can fix this.

The correct next step is a new hypothesis with a new mechanism on a new branch,
not further experimentation with this candidate.

## Immutable Research Record

- FLOW_SPREAD_03_STATUS.md: final status, 3-capture assessment
- Config sha256 6d43d31d: frozen, never modified
- OOS captures: untouched, no relabeling
- NO_DEPLOY: permanently locked