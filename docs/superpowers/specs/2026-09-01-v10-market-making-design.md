# V10 Execution-Aware Market-Making Research Design

**Date:** 2026-09-01  
**Repository:** `yogeshnamdhari-commits/binance_orderflow_autotrader_v2`  
**Branch:** `research/v10-market-making-design`  
**Status:** DESIGN ONLY — NO PRODUCTION CODE / NO LIVE TRADING

## 1. Decision Context

The frozen V5-V9 research program established that the existing BTCUSDT directional information set contains statistically detectable short-horizon information but has not demonstrated positive net expectancy after realistic execution costs. The strongest previously identified microstructure candidate was large-trade direction, but its gross edge remained below the economic requirement and its signal count was small. The project therefore must not respond by adding another large collection of directional predictors or by relaxing the economic gate.

V10 changes the economic question rather than merely increasing model complexity:

> Can the strategy identify states in which providing passive liquidity has positive expected value after maker fees/rebates, spread capture, adverse selection, fill probability, queue position, latency, cancellations, inventory risk, and eventual inventory liquidation costs?

This is a new hypothesis. It does not invalidate or overwrite V5-V9 negative evidence.

## 2. Research Boundary

V10 is initially a **data-collection and empirical market-making study**, not a live trading system.

Hard constraints:

- `main` remains the frozen production baseline.
- The stale `research/v9-orderflow-build` branch is not merged.
- V10 code remains isolated from production until all gates pass.
- No API key is required for research replay.
- No live order placement is permitted.
- Paper trading is permitted only after the replay/economic gates pass.
- No parameter is tuned on the final OOS sample.
- A failed V10 hypothesis is recorded as failure; it is not rescued by threshold fishing.

## 3. Economic Objective

For a passive order posted at side `s` and price `p_q`, define the expected incremental value over its decision horizon as:

`EV = P(fill) * [spread_capture + fee_rebate - adverse_selection - inventory_cost - exit_cost] - cancellation/opportunity_cost`

The exact implementation must decompose the terms rather than use a single fitted black-box PnL target.

A candidate order is eligible only when a conservative lower-bound estimate of EV is positive.

The model must distinguish:

1. **execution probability** — whether the order fills;
2. **conditional post-fill return** — what happens after the fill;
3. **inventory liquidation value** — cost/value of closing inventory;
4. **queue position** — expected time and probability of reaching execution;
5. **latency** — state deterioration between observation, decision, submission, and acknowledgement;
6. **adverse selection** — price movement against the maker conditional on being filled.

The literature specifically motivates this decomposition: queue position affects adverse-selection risk and inventory management, and empirical Binance perpetual research reports a trade-off between maker fill likelihood and post-fill returns. These are hypotheses for V10, not guarantees of profitability.

## 4. Required Data

### 4.1 Exchange event data

Collect authentic Binance BTCUSDT perpetual data with:

- exchange event timestamp;
- local receipt timestamp;
- message type;
- update/sequence identifiers where provided;
- trade price;
- trade quantity;
- aggressor direction where inferable from exchange semantics;
- best bid/ask;
- multi-level bid/ask depth;
- depth update events;
- add/remove/modify information when available from the feed semantics;
- spread;
- mid-price;
- microprice;
- reconnect/gap state.

### 4.2 Local-state telemetry

For every research decision point, record:

- event-to-event latency;
- local processing latency;
- observed book age;
- feed gap flags;
- book reconstruction status;
- quote state at decision;
- quote state immediately before submission;
- simulated acknowledgement latency;
- simulated queue state;
- cancellation timestamp.

### 4.3 Historical limitation

If historical L2/L3 data cannot be obtained with sufficient integrity, V10 must not fabricate historical queue position or fill probabilities. The first implementation milestone is therefore a validated live data recorder and deterministic replay dataset.

## 5. Book Reconstruction Requirements

The recorder/replayer must enforce:

- sequence continuity where applicable;
- deterministic ordering for equal timestamps;
- snapshot/update reconciliation;
- crossed/locked-book diagnostics;
- negative-size rejection;
- duplicate-event detection;
- stale-event detection;
- reconnect segmentation;
- clock-domain separation between exchange time and local receipt time.

A data-quality failure must invalidate the affected interval rather than silently repairing it with future information.

## 6. V10 State Variables

The initial feature set is deliberately small and mechanism-driven.

### A. Price state

- mid-price return over 10ms, 25ms, 50ms, 100ms, 250ms, 500ms;
- microprice minus mid-price;
- short-horizon realized volatility;
- short-horizon signed price acceleration.

These are state variables, not independent hypotheses to be searched freely.

### B. Queue state

At each quoted side:

`queue_ahead = displayed_size_at_quote + estimated_relevant_replenishment`

When exact individual queue position is unavailable, use an explicitly conservative queue-position proxy based only on observable events. The proxy must be validated against known exchange matching semantics.

Derived variables:

- normalized queue ahead;
- queue depletion rate;
- queue replenishment rate;
- queue cancellation rate;
- queue survival time;
- queue rank change.

### C. Flow/adverse-selection state

- signed aggressive trade flow;
- large-trade intensity;
- short-horizon flow persistence;
- flow acceleration;
- trade arrival intensity;
- price response conditional on signed flow;
- post-trade continuation/reversal state.

### D. Liquidity state

- spread in ticks/bps;
- depth at L1/L5/L10;
- depth slope;
- depth depletion;
- depth replenishment;
- book resiliency;
- bid/ask asymmetry;
- liquidity withdrawal rate.

### E. Inventory state

- current inventory;
- inventory as fraction of predefined risk limit;
- inventory age;
- mark-to-market PnL;
- expected liquidation cost;
- inventory directional pressure.

## 7. Core Empirical Hypotheses

### HMM-1: Fill Probability

**Question:** Can observable queue and order-flow state estimate the probability that a passive order fills within a fixed horizon better than a naive baseline?

Target:

`Y_fill(h) = 1 if the order receives a fill within h, else 0`

Initial horizons: 50ms, 100ms, 250ms, 500ms, 1s, 2s.

Required baselines:

- unconditional fill rate;
- quote-level fill rate;
- queue-size-only model;
- queue + event-rate model.

Acceptance is based on OOS calibration and log loss/Brier score, not AUC alone.

### HMM-2: Conditional Adverse Selection

**Question:** Conditional on a passive fill, does the pre-fill state predict the subsequent mid-price movement relative to the fill price?

Target:

`AS(h) = side-adjusted return from fill price to mid-price at h after fill`

Evaluate both mean and lower-tail behavior.

The hypothesis fails if fill probability improves but post-fill returns deteriorate enough that net EV remains non-positive.

### HMM-3: Fill-vs-Return Trade-off

**Question:** Is there a stable state-dependent trade-off between probability of fill and post-fill return?

Estimate jointly:

`P(fill | X)`

and

`E[AS(h) | fill, X]`

The purpose is not to maximize either component independently. The decision variable is their economic product after costs.

### HMM-4: Quote-Side Selection

**Question:** Given the same market state, does choosing bid versus ask using predicted adverse selection and inventory state improve net EV over symmetric quoting?

The policy must include a NO-QUOTE state.

### HMM-5: Cancellation/Quote-Refresh Value

**Question:** Does cancelling or refreshing a passive quote when queue/adverse-selection state deteriorates improve net value after lost queue priority is accounted for?

Cancellation decisions must explicitly include the opportunity cost of abandoning queue position.

### HMM-6: Inventory-Aware Market Making

**Question:** Can inventory penalties improve net expectancy without creating a hidden directional strategy?

The inventory term must be economically interpretable and pre-registered. It cannot simply be tuned until historical PnL improves.

## 8. Execution Simulator

The simulator is a central research component, not a cosmetic backtest layer.

For every simulated order:

1. capture observable state;
2. apply decision latency;
3. apply submission latency;
4. determine whether the quote remains valid;
5. estimate queue ahead;
6. consume queue according to subsequent market events;
7. process cancellations/replenishment;
8. generate partial fills where applicable;
9. mark adverse selection after each fill;
10. calculate eventual inventory exit cost;
11. include fees/rebates and spread capture;
12. record the complete order lifecycle.

A backtest that assumes every touched quote fills is prohibited.

## 9. Fill Model Policy

Use the simplest empirically defensible model first.

Stage 1:
- event-driven deterministic queue simulation where exchange semantics permit it.

Stage 2, only if required:
- calibrated stochastic residual model for unobservable queue behavior.

The stochastic model must be calibrated only on training data and validated on unseen chronological data.

The simulator must report sensitivity under:

- optimistic fill assumptions;
- central measured assumptions;
- conservative fill assumptions.

A strategy that is profitable only under optimistic fills fails the economic gate.

## 10. Latency Model

Latency must be decomposed into:

`L_total = L_market_data + L_decision + L_submission + L_exchange_ack`

Where measured components are available, use measured distributions rather than fixed constants.

For historical replay, latency must be sampled from a pre-registered distribution estimated from a separate calibration period. No OOS latency calibration is allowed.

Latency sensitivity must be reported at minimum at the 10th, 50th, 90th and 99th percentiles of the measured distribution.

## 11. Economic Accounting

Every filled order must produce:

`gross_spread_capture`

`maker_fee_or_rebate`

`markout_10ms`

`markout_50ms`

`markout_100ms`

`markout_250ms`

`markout_500ms`

`markout_1s`

`markout_2s`

`inventory_exit_cost`

`slippage`

`net_pnl`

The primary economic metric is **net PnL per unit of executed notional**, not gross spread captured.

## 12. Statistical Design

All primary hypotheses and horizons are frozen before final OOS evaluation.

Use:

- chronological train/validation/test partitions;
- purged walk-forward splits where overlapping horizons require it;
- session-level bootstrap confidence intervals;
- block bootstrap where serial dependence requires it;
- placebo/permutation tests;
- multiple-testing correction across explicitly registered hypotheses;
- calibration diagnostics for probability forecasts;
- regime/session stability analysis.

Pooled observations must not be treated as independent when serial dependence or session clustering invalidates that assumption.

## 13. No-Parameter-Fishing Rules

Prohibited:

- selecting the best horizon after observing OOS PnL;
- changing queue thresholds after OOS results;
- changing inventory limits after OOS results;
- trying many quote offsets and retaining the winner without correction;
- optimizing cancellation thresholds against the final OOS period;
- choosing the best latency scenario retrospectively;
- adding features because they improve the OOS result;
- changing the economic gate after seeing the outcome.

If multiple variants are scientifically necessary, they must be registered as separate candidates and corrected statistically.

## 14. Economic Acceptance Gate

A V10 policy is deployable only if **all** conditions pass.

### G1 — Positive net expectancy

`mean(net_pnl_per_notional) > 0`

after measured fees/rebates, realistic fill behavior, latency, adverse selection and inventory liquidation.

### G2 — Confidence

The lower bound of the pre-specified confidence interval for net expectancy must be above zero.

### G3 — Walk-forward persistence

Positive net expectancy must survive chronological OOS/walk-forward evaluation and cannot be driven by one session.

### G4 — Execution robustness

The strategy must remain economically viable under the predefined central and conservative execution scenarios.

### G5 — Fill-model robustness

The result cannot depend on an unrealistically favorable fill model.

### G6 — Latency robustness

The result cannot disappear under the measured upper-tail latency scenarios that are representative of actual operation.

### G7 — Inventory robustness

Inventory must remain within predefined risk bounds and liquidation costs must not erase the edge.

### G8 — Incremental information

The market-making decision must demonstrate incremental economic value relative to:

1. symmetric passive quoting;
2. static quote/no-refresh baseline;
3. inventory-only baseline;
4. simple spread/volatility gating baseline.

### G9 — Operational integrity

Data-quality, reconciliation, kill-switch, duplicate-order prevention and position-accounting tests must pass independently.

If any gate fails, classification is `NO_DEPLOYABLE_EDGE`.

## 15. Required Baselines

Before claiming V10 alpha, compare against:

### B0 — No-trade
Expected net PnL = 0; establishes the economic null.

### B1 — Symmetric touch quoting
Quote both sides at the best bid/ask under fixed risk limits with no predictive model.

### B2 — Inventory-only quoting
Adjust side selection using inventory state only.

### B3 — Spread/volatility filter
Quote only under pre-registered liquidity/spread/volatility conditions.

### B4 — V10 predictive policy
Uses only registered predictive state variables and the execution model.

The predictive policy must demonstrate incremental value over B1-B3, not merely positive PnL in isolation.

## 16. Required Reports

V10 research must generate:

- data-quality report;
- event-reconstruction audit;
- latency calibration report;
- fill-model calibration report;
- queue-model validation report;
- markout/adverse-selection report;
- fill-vs-return trade-off report;
- inventory-risk report;
- execution-cost report;
- chronological OOS report;
- robustness report;
- multiple-testing report;
- final economic-gate report.

## 17. Repository Isolation

Initial V10 files should be confined to research/design infrastructure, for example:

- `docs/superpowers/specs/2026-09-01-v10-market-making-design.md`
- `research/v10_*.py`
- `tests/test_v10_*.py`
- `data/v10/` or an equivalent excluded research-data location.

No production decision/execution file should be modified during the first research milestone.

## 18. Implementation Sequence

### Phase 1 — Data recorder

Build deterministic Binance event capture with exchange/local timestamps and integrity diagnostics.

### Phase 2 — Replay engine

Reconstruct the book and trades deterministically from captured data.

### Phase 3 — Passive-order lifecycle simulator

Model queue position, fills, partial fills, cancellation, latency and markouts.

### Phase 4 — Baseline market-making policies

Implement B0-B3 and validate simulator behavior before introducing predictive models.

### Phase 5 — Registered predictive hypotheses

Implement HMM-1 through HMM-6 without OOS tuning.

### Phase 6 — Walk-forward evaluation

Run the frozen statistical/economic protocol.

### Phase 7 — Decision

Output exactly one of:

- `DEPLOYABLE_EDGE`
- `NO_DEPLOYABLE_EDGE`
- `DATA_INSUFFICIENT`

No intermediate label permits live trading.

## 19. Research Basis

The design is motivated by established market-microstructure and market-making research. Recent empirical work on Binance Bitcoin perpetuals reports a negative relationship between maker fill likelihood and post-fill returns, highlighting the need to model fill probability and adverse selection jointly. Research on limit-order queues shows that queue position affects adverse-selection risk and inventory management. Work on queue valuation likewise treats positional value as a combination of immediate spread/adverse-selection economics and future queue optionality. Research on execution simulation warns that unrealistic fill probabilities and adverse fills can materially overstate short-horizon strategy performance.

These studies motivate the research questions. They do **not** establish that V10 is profitable.

## 20. Explicit Non-Goals

V10 will not:

- claim profitability from gross spread capture;
- assume all touched quotes fill;
- ignore adverse selection;
- ignore queue position;
- ignore latency;
- ignore partial fills;
- ignore inventory liquidation;
- optimize dozens of hyperparameters;
- overwrite V5-V9 negative conclusions;
- enable live trading before all gates pass.

## 21. Final Research Principle

The objective of V10 is not to find a backtest that looks profitable.

The objective is to determine whether **realistic passive liquidity provision contains an economically exploitable state-dependent edge that survives execution realism and chronological out-of-sample validation**.

If the answer is no, the scientifically correct result remains `NO_DEPLOYABLE_EDGE`.
