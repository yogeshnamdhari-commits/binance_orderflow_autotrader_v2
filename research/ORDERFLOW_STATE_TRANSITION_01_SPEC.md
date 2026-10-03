# ORDERFLOW_STATE_TRANSITION-0.1 — Preregistration

**Status:** PREREGISTERED — AMENDED A-002 BEFORE DATA COLLECTION  
**Registration date:** 2026-10-03  
**Instrument:** BTCUSDT  
**Market:** Binance USD-M Futures  
**Contract:** Perpetual  
**Live order submission:** FALSE  
**Branch:** `research/orderflow-state-transition-01`  
**Base repository commit:** `1003b958849ebbc7e453fefad3946346f932b0dd`

## 1. Research question

Does a **transition into a persistent, aligned multi-level order-flow state** predict the direction of the BTCUSDT perpetual over the next 5 seconds strongly enough to remain economically positive under a conservative, explicitly executable taker benchmark?

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

Four new sessions are required:

| Capture | Purpose | Use |
|---|---|---|
| 1 | Development / pipeline verification | May be inspected for implementation correctness only |
| 2 | Untouched OOS | Economic/statistical evaluation |
| 3 | Untouched OOS | Economic/statistical evaluation |
| 4 | Untouched OOS | Economic/statistical evaluation |

Target duration: **60 minutes per session**.

Sessions must be non-overlapping and must begin after this preregistration commit. The exact clock times are recorded in UTC in the evidence manifest.

No parameter may be selected from captures 2, 3, or 4.

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

## 8. Economic gate — Amendment A-002

The current benchmark uses the regular-user BTCUSDT USDⓈ-M Futures taker fee of **5.0 bps per side**, with no discount assumed. Binance's published USDⓈ-M Futures schedule currently lists **0.0200% maker / 0.0500% taker** for regular USDT-margined futures users. citeturn251206search0

### 8.1 Fixed cost components

- Entry taker fee: **5.0 bps**
- Exit taker fee: **5.0 bps**
- Round-trip trading fees: **10.0 bps**
- Safety buffer: **2.0 bps**
- Funding: included only if the modeled 5-second holding interval actually crosses a funding settlement; otherwise zero. Binance documents funding as a payment between position holders at the applicable settlement time. citeturn428443search1turn428443search5

No fixed 1.0 bps spread, 1.0 bps slippage, or 2.0 bps adverse-selection haircut is assumed ex ante. Those values would be arbitrary point estimates for this preregistration.

### 8.2 Deterministic executable benchmark

Reference notional: **100 USDT per signal**.

For each scored signal, construct both a mid-to-mid diagnostic and an executable book benchmark from the captured reconstructed top-10 book:

1. **Signal timestamp:** the third consecutive confirming depth event.
2. **Entry snapshot:** the first valid reconstructed book snapshot strictly after the signal timestamp.
3. **Entry execution:** consume displayed ask depth for LONG or bid depth for SHORT until exactly 100 USDT notional is filled; calculate VWAP from the captured levels.
4. **Exit snapshot:** the first valid reconstructed book snapshot at or after signal timestamp + 5 seconds.
5. **Exit execution:** consume displayed bid depth for LONG or ask depth for SHORT until the same 100 USDT notional is closed; calculate VWAP.
6. If either leg cannot fill the complete 100 USDT notional from available captured depth, mark the outcome unresolved and exclude it from economic scoring; record the exclusion.

This executable benchmark therefore incorporates the observed spread and displayed-depth price impact. It does not assume zero spread, zero slippage, or instantaneous mid-price execution.

### 8.3 Adverse selection treatment

Adverse selection is **measured diagnostically, not subtracted as a fixed haircut**.

Define an adverse-selection diagnostic as the subsequent 5-second directional mid-price movement from the executable entry reference. This diagnostic is reported separately so that adverse selection is not double-counted inside the executable return and again as an arbitrary cost.

A separate passive-maker hypothesis would require its own preregistration because maker-fill selection and queue position are materially different from the present taker benchmark.

### 8.4 Net economics

Definitions:

```text
gross_bps             = directional mid-to-mid return over 5 s
executable_gross_bps = directional return from executable entry/exit VWAPs
fee_bps               = 10.0
funding_bps           = realized funding debit/credit over the modeled hold
safety_buffer_bps     = 2.0
net_bps               = executable_gross_bps - fee_bps - funding_bps - safety_buffer_bps
```

The safety buffer is included directly in `net_bps` so the pass criterion can use a single net-edge definition.

### 8.5 Primary economic pass

All conditions must pass:

```text
1. 95% block-bootstrap CI lower bound of pooled OOS mean net_bps > 0
2. Mean net_bps > 0 in OOS session 2
3. Mean net_bps > 0 in OOS session 3
4. Mean net_bps > 0 in OOS session 4
5. At least 30 scored signals in each OOS session
6. At least 90 scored signals pooled across the three OOS sessions
```

These signal-count floors are minimum evidence requirements, not a formal claim of statistical power.

## 9. Statistical procedure — Amendment A-002

Primary inference remains the **5-second horizon**.

Use a **clock-time block bootstrap**, not event-count blocks, because information arrival is irregular.

- OOS evidence: sessions 2, 3, and 4 only
- Block construction: contiguous **300-second clock-time blocks**
- Resamples: **10,000**
- Seed: **20261003**
- Confidence interval: **two-sided 95% percentile bootstrap CI**
- Primary statistic: pooled OOS mean `net_bps`
- Also report per-session means and counts

Do not use an IID t-statistic as the primary inference.

Capture 1 remains development-only. It cannot select thresholds, alter the signal rule, choose the cost model, or determine the OOS decision. Captures 2, 3, and 4 remain untouched OOS.

### 9.0 Timestamp and execution-record contract

Each scored signal must retain a machine-readable evidence row containing at minimum:

- `signal_time_exchange_ms`
- `book_snapshot_age_ms`
- `entry_snapshot_delay_ms`
- `entry_vwap_price`
- `exit_vwap_price`
- `gross_bps`
- `executable_gross_bps`
- `fee_bps`
- `funding_bps`
- `net_bps`
- `book_depth_sufficient`
- `exclusion_reason` when the outcome is unresolved/excluded

The signal-time book age is measured between the signal timestamp and the reconstructed book timestamp used to evaluate the state. Under the registered event-driven reconstruction this should normally be zero because the signal is generated from the current depth event. The economically relevant execution-latency diagnostic is `entry_snapshot_delay_ms`, measured from signal time to the first subsequent valid book snapshot used for entry.

No arbitrary stale-book millisecond cutoff is introduced by this amendment. A signal is invalid for executable scoring when the required post-signal entry snapshot or +5-second exit snapshot cannot be resolved from valid captured data; the reason must be recorded rather than silently dropped.

### 9.1 Results table contract

| Metric | Definition |
|---|---|
| `gross_bps` | Directional mid-to-mid 5-second return |
| `executable_gross_bps` | Directional 5-second return using captured-book VWAP entry/exit |
| `fee_bps` | Fixed 10.0 bps taker/taker commission benchmark |
| `funding_bps` | Funding debit/credit actually crossing settlement, if any |
| `net_bps` | Executable gross minus fees, funding, and 2.0 bps safety buffer |
| `net_bps_lower_95` | Lower endpoint of pooled 95% clock-block bootstrap CI |
| `adverse_selection_bps` | Separate diagnostic; not an additional fixed haircut |
## 10. Controls and leakage prevention

The following are prohibited:

- Using future trades, future depth, or future mark price in feature construction.
- Recomputing a normalization window using future observations.
- Selecting thresholds from captures 2, 3, or 4.
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

## 11.1 Transport-error accounting

The collector does not perform automatic reconnects during a scored capture. Therefore, a nonzero `reconnects` value must not be inferred merely because a WebSocket raises an exception during normal scheduled shutdown. The implementation records an actual in-interval feed transport failure separately as `transport_errors`, with the feed, exception type, message, and timestamp. A capture is invalid when an actual transport error occurs during the scored interval.

The development Capture 1 that reported `reconnects=3` after a full-duration run is retained as invalid evidence because the recorded manifest is immutable. The collector has since been corrected so that intentional shutdown is not misclassified as a reconnect/transport failure.


## 11.5 Pre-capture synthetic measurement audit

Before Capture 1 is collected, run `research/test_orderflow_state_transition_math.py` on the research branch. This synthetic audit checks deterministic VWAP construction, fixed-quantity exit handling, LONG/SHORT symmetry, taker-fee normalization, funding as a separate cost component, and fail-closed behavior on insufficient displayed depth. It uses no research captures or external market data and does not affect the preregistered research result.



## 11.6 Development Capture 1 transport failure and correction

The first development Capture 1 was **INVALID / NOT RESEARCH EVIDENCE**. Depth transport completed with a valid bridge and no sequence gaps, but the captured session reported **zero aggTrade events and zero markPrice@1s events**, causing `capture_valid=false`. No OOS decision or parameter choice was based on that capture.

The implementation was corrected before any OOS capture by migrating to Binance's current USDⓈ-M category-specific WebSocket endpoints: high-frequency public data such as `depth@100ms` uses `wss://fstream.binance.com/public/ws/...`, while regular market data such as `aggTrade` and `markPrice@1s` uses `wss://fstream.binance.com/market/ws/...`. Binance announced this base-URL split and the retirement of legacy WebSocket paths for USDⓈ-M Futures. citeturn403631search0turn520081search0

A short non-research diagnostic `research/diagnose_orderflow_streams.py` must pass with at least one valid event from **each** required feed before Capture 1 is rerun. The diagnostic writes no research capture and does not alter the hypothesis.

## 11.7.1 Capture 1 scorer audit correction

The initial Capture 1 scoring run exposed a specification-to-code discrepancy: the scorer standardized the per-depth-event OFI values directly, whereas the preregistration requires 500 ms rolling OFI sums (OFI_1, OFI_5, OFI_10) to be normalized using the strictly prior 60-second median/MAD window.

The Capture 1 scoring output of 86 signals is therefore **pipeline diagnostic output only and is not valid evidence of the registered state-transition rule**. The immutable raw Capture 1 remains valid development data.

The scorer was corrected before any OOS scoring. Synthetic tests now include an explicit 500 ms time-window aggregation test. No OOS capture has been scored or used to tune the correction.

## 11.7 Frozen scoring implementation

The frozen scoring implementation is `research/score_orderflow_state_transition.py`.

It verifies the capture manifest and both evidence-file SHA-256 fingerprints **before reading them**. Book state is read exclusively from `book_snapshots.jsonl`; the scorer never reconstructs the book from `events.jsonl` for signal-time execution. `events.jsonl` is used only for the required `aggTrade` aggressive-flow feature and `markPrice@1s` funding records.

The multi-level OFI calculation is the repository's existing definition in `app/v7_true_features.py` (`compute_multi_level_ofi`): per-level changes are derived from consecutive book snapshots and net OFI is bid change minus ask change. The Phase 3 scorer uses the first 1, 5, and 10 per-level values as the registered `OFI_1`, `OFI_5`, and `OFI_10` inputs to the rolling sums.

Synthetic scorer tests are in `research/test_orderflow_state_transition_scorer.py`.

Scoring Capture 1 is permitted only for implementation validation. Economic results from Capture 1 must not be used to modify the hypothesis. OOS scoring is performed only after Captures 2, 3, and 4 have all passed manifest integrity checks and are frozen.

## 12. Required evidence outputs

The implementation must produce, at minimum:

- raw session manifest
- reconstructed-book integrity summary
- event counts by feed
- excluded-event counts and reasons
- signal count by direction
- gross bps mean/median
- executable gross bps mean/median
- net bps mean/median
- adverse-selection diagnostic mean/median
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
4 fresh sessions (1 development + 3 untouched OOS)
   |
   +--> integrity failure --------------------> INVALID / STOP
   |
   v
Frozen rule applied
   |
   v
Untouched OOS (captures 2+3+4)
   |
   +--> pooled 95% CI lower bound(net) <= 0 -> CLOSED / REJECTED
   |
   +--> any OOS session mean net <= 0 --------> CLOSED / REJECTED
   |
   +--> insufficient OOS signal count --------> CLOSED / REJECTED
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

## 16. Amendment A-001 — Superseded economic clarification

**Amendment status:** Registered before Capture 1 data collection.

Reason for amendment: the original 3.4 bps round-trip execution assumption did not explicitly represent both taker legs and did not separately define spread, displayed-depth price impact, funding, or an executable entry/exit timestamp. The amendment corrects the economic benchmark without changing the registered signal logic, state thresholds, persistence rule, cooldown, primary 5-second horizon, required feeds, session roles, or no-live-order constraint.

The amendment is based on Binance's current published USDⓈ-M Futures fee schedule and funding documentation as checked on **2026-10-03**.

This amendment is **superseded by Amendment A-002** below. It is retained for audit history only.
## 17. Amendment A-002 — execution-cost and statistical clarification

**Amendment status:** Registered before Capture 1 data collection.

Reason for amendment: the prior specification used a 3.4 bps round-trip fee assumption and point-estimate economic tests. This amendment replaces that assumption with the current regular-user taker/taker benchmark, measures spread and displayed-depth impact directly from the captured book, treats adverse selection as a separate diagnostic rather than an arbitrary additive haircut, adds a three-session untouched OOS requirement, and changes the bootstrap construction to 300-second clock-time blocks.

Because the original three-session design contained only two untouched OOS sessions, Capture 4 is now required so that the amended requirement of three independent OOS sessions is internally consistent.

This amendment does not change the registered signal features, thresholds, persistence rule, cooldown, primary 5-second horizon, required market feeds, or no-live-order constraint.