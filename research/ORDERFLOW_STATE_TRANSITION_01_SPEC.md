# ORDERFLOW_STATE_TRANSITION-0.1 — Preregistration

**Status:** PREREGISTERED  
**Registration date:** 2026-10-03  
**Instrument:** BTCUSDT  
**Market:** Binance USD-M Futures  
**Contract:** Perpetual  
**Live order submission:** FALSE  
**Branch:** `research/orderflow-state-transition-01`  
**Base repository commit:** `1003b958849ebbc7e453fefad3946346f932b0dd`

## 1. Research question

Does a **transition into a persistent, aligned multi-level order-flow state** predict the direction of the BTCUSDT perpetual mid-price over the next 5 seconds, after a fixed taker-cost and safety-buffer hurdle?

This is intentionally different from testing a single static book-imbalance threshold. The object under test is the **state change and persistence** of order-flow pressure.

The literature motivating the design reports short-horizon price impact from order-flow imbalance and evidence that multi-level order-flow information can add information beyond the best quote. These studies are not evidence that this BTCUSDT hypothesis will be profitable; they only motivate the measurable research question. citeturn747263academia0turn747263academia1

## 2. Data contract

Collect **fresh data after this registration**. Previously inspected captures cannot be reused as development or OOS evidence for this hypothesis.

Required feeds, all for BTCUSDT USD-M perpetual:
- `depth@100ms`
- `aggTrade`
- `markPrice@1s`

Binance's current USD-M WebSocket documentation supports live subscriptions including `btcusdt@aggTrade` and `btcusdt@depth`. citeturn771707search1

### Book integrity

A capture is valid only after:
1. REST/WebSocket depth snapshot is acquired.
2. Pre-snapshot depth events are bridged according to sequence rules.
3. Subsequent depth updates are applied in sequence.
4. No sequence gap occurs.
5. No reconnect occurs during the scored interval.
6. All scored observations retain exchange timestamps and source provenance.

Any failed integrity condition invalidates the session. Missing values are **not** converted to zero.

The repository's production data contract already requires exchange-traceable observations, valid timestamps, freshness, and provenance-preserving derived data.

## 3. Session design

Three new sessions are required:

| Capture | Purpose | Use |
|---|---|---|
| 1 | Development / pipeline verification | May be inspected for implementation correctness only |
| 2 | Untouched OOS | Economic/statistical evaluation |
| 3 | Untouched OOS | Economic/statistical evaluation |

Target duration: **60 minutes per session**.

Sessions must be non-overlapping and must begin after this preregistration commit. The exact clock times are recorded in UTC in the evidence manifest.

No parameter may be selected from captures 2 or 3.

## 4. Event reconstruction

All features are evaluated at the timestamp of a valid depth event.

### 4.1 Multi-level order-flow imbalance

Reconstruct the top 10 book levels from the depth stream.

For each level and depth event, compute signed queue-flow changes from the previous reconstructed book. For bid liquidity, additions/improvements are positive and removals/worsening are negative. For ask liquidity, the sign is reversed so that positive values represent net demand-side pressure.

Compute rolling 500 ms sums:
- `OFI_1`
- `OFI_5`
- `OFI_10`

where the suffix denotes the number of price levels included.

### 4.2 Aggressive trade imbalance

From `aggTrade`, classify:
- `m = false` → aggressive buy quantity
- `m = true` → aggressive sell quantity

The repository's existing Binance order-flow implementation uses this same taker-side convention. Binance's current market-trade documentation also defines `m` as the maker-side indicator. citeturn771707search3

For each 500 ms window:

```
A_500 = (buy_qty - sell_qty) / (buy_qty + sell_qty)
```

If the denominator is zero, `A_500` is unavailable and the event cannot trigger a signal.

### 4.3 Robust normalization

For each of `OFI_1`, `OFI_5`, and `OFI_10`, compute a trailing robust z-score using only observations strictly earlier than the current event:

```
z = (x - rolling_median) / (1.4826 * rolling_MAD)
```

Trailing window: **60 seconds**.

If the rolling MAD is zero or unavailable, the normalized value is unavailable and the event cannot trigger.

This normalization rule is fixed. It is not tuned on OOS data.

## 5. Fixed state definition

An event is in the **ALIGNED_EXTREME** state when all conditions are simultaneously true:

1. `sign(z_OFI_1) = sign(z_OFI_5) = sign(z_OFI_10)`
2. `sign(z_OFI_1) = sign(A_500)`
3. `abs(z_OFI_1) >= 1.0`
4. `abs(z_OFI_5) >= 1.0`
5. `abs(z_OFI_10) >= 1.0`
6. `abs(A_500) >= 0.60`
7. All four directional components are finite and source-valid.

State direction is LONG for positive alignment and SHORT for negative alignment.

## 6. Transition rule

A signal is generated only on a **transition into** the aligned state:

- At least one of the immediately preceding 500 ms observations was not `ALIGNED_EXTREME` in the same direction.
- The current direction remains `ALIGNED_EXTREME` for **3 consecutive 100 ms depth events**.
- The signal timestamp is the timestamp of the third confirming event.

This prevents the test from counting a long-lived extreme state repeatedly as separate discoveries.

### Cooldown

After a signal, suppress additional signals for **5 seconds**.

A later signal is permitted only after the cooldown ends and a new transition satisfying the same rule occurs.

No discretionary entries are allowed.

## 7. Outcome definition

### Primary horizon

**5 seconds**.

For a LONG signal:

```
gross_bps = (mid[t+5s] / mid[t] - 1) * 10,000
```

For a SHORT signal:

```
gross_bps = (mid[t] / mid[t+5s] - 1) * 10,000
```

where:

```
mid[t] = (best_bid[t] + best_ask[t]) / 2
```

The first valid mid-price at or after the target timestamp is used. If the horizon cannot be resolved from valid market observations, the observation is excluded from scored outcomes and the exclusion is recorded.

### Secondary horizons

10 s and 30 s may be reported descriptively.

They **cannot** be used to choose parameters, alter the rule, or overturn the primary 5 s economic decision.

## 8. Economic gate

Use the established BTCUSDT taker reference:

- Round-trip cost: **3.4 bps**
- Safety buffer: **2.0 bps**
- Minimum gross edge: **5.4 bps**

For each scored observation:

```
net_bps = gross_bps - 3.4
```

### Primary economic candidate condition

The hypothesis is economically promising only when **pooled untouched OOS** satisfies both:

```
gross_bps > 5.4
net_bps   > 0
```

OOS session-level gross and net results are mandatory for the audit record.

A positive result below 5.4 bps is **not** an economic pass.

## 9. Statistical procedure

Use a **block bootstrap** over OOS signal outcomes to account for serial dependence.

- Block length: 5 seconds
- Resamples: 10,000
- Seed: 20261003
- Report 95% confidence intervals for pooled OOS gross and net edge.
- Preserve signal order within bootstrap blocks.

No alternative bootstrap configuration may be selected after seeing the result.

## 10. Controls and leakage prevention

The following are prohibited:

- Using future trades, future depth, or future mark price in feature construction.
- Recomputing a normalization window using future observations.
- Selecting thresholds from captures 2 or 3.
- Changing the 5-second primary horizon after OOS inspection.
- Adding funding, open interest, liquidations, cross-venue data, ML models, news, or extra indicators after registration.
- Reusing previously inspected OOS captures for this hypothesis.
- Sending live orders.
- Modifying any frozen/rejected strategy candidate.

Synthetic or estimated trade events are excluded. Ticker-derived placeholders are not valid order-flow evidence.

## 11. Data-quality stop conditions

Stop and classify the capture as invalid if any of the following occurs:

- depth sequence gap
- reconnect during the scored interval
- bootstrap not bridged
- missing required feed
- invalid/malformed event timestamps
- non-monotonic reconstructed book state that violates feed integrity
- provenance missing from scored inputs

Do not repair an invalid session by guessing or backfilling synthetic values.

## 12. Required evidence outputs

The implementation must produce, at minimum:

- raw session manifest
- reconstructed-book integrity summary
- event counts by feed
- excluded-event counts and reasons
- signal count by direction
- gross bps mean/median
- net bps mean/median
- pooled OOS gross and net
- 95% block-bootstrap CIs
- per-session OOS gross/net
- exact code commit SHA
- exact configuration/spec hash
- dataset/session fingerprints
- explicit economic decision: `ECONOMIC_CANDIDATE = TRUE/FALSE`
- explicit deployment state: `NO_DEPLOY`

## 13. Decision tree

```
PREREGISTER
   |
   v
3 fresh sessions
   |
   +--> integrity failure --------------------> INVALID / STOP
   |
   v
Frozen rule applied
   |
   v
Untouched OOS (captures 2+3)
   |
   +--> pooled gross <= 5.4 bps ------------> CLOSED / REJECTED
   |
   +--> pooled net <= 0 ---------------------> CLOSED / REJECTED
   |
   v
ECONOMIC_CANDIDATE = TRUE
   |
   v
Further statistical / forward / production validation
   |
   v
Only after every independent gate passes:
LIVE AUTHORIZATION
```

Passing the economic gate does **not** certify live trading.

## 14. Why this hypothesis is distinct

The prior order-flow scan tested scalar contemporaneous features such as static book imbalance and microprice displacement across horizons. This preregistration changes the research object to **dynamic state transition**:

```
non-aligned / neutral state
        ↓
multi-level OFI alignment
        ↓
trade-flow confirmation
        ↓
3-event persistence
        ↓
5 s forward price response
```

The purpose is to test whether the *change in order-book state*, rather than a single extreme snapshot, carries incremental short-horizon information.

## 15. Deployment status

```
ECONOMIC_CERTIFICATION = NOT_CERTIFIED
LIVE_AUTHORIZATION      = BLOCKED
DEPLOYMENT              = NO_DEPLOY
```

This document is the fixed preregistration. Any change to a registered parameter or rule requires a new hypothesis ID and a new branch.
