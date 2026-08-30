# V9 Order-Flow Algorithm Design

**Date:** 2026-08-30  
**Repository:** `yogeshnamdhari-commits/binance_orderflow_autotrader_v2`  
**Branch:** `research/v9-orderflow-build`

## Objective

Build a new research-backed order-flow trading system from the frozen V5/V6 baseline without modifying their historical conclusions. The objective is not to force a positive backtest; it is to determine whether a causally valid, execution-aware information set can produce a statistically and economically viable short-horizon BTCUSDT futures strategy.

## Existing Evidence

The repository's frozen V5/V6 work establishes that the existing feature set contains predictive information but not enough gross expectancy to overcome measured trading costs. The strongest previously tested research hypothesis, large-trade direction, produced 1.591 bps gross but remained negative after maker costs and had only 885 OOS signals. The current baseline therefore remains a control, not the next production strategy.

The repository also records that funding/basis information at hourly/8-hour resolution did not add meaningful incremental information for sub-minute trading, while high-frequency cross-venue historical data was unavailable. These are constraints on the initial V9 information set rather than assumptions to be silently ignored.

## Recommended Architecture

### 1. Data Layer

Use authentic Binance exchange-event data with exchange timestamps and local receipt timestamps. Maintain deterministic reconstruction of the local L2 book and trade stream. Preserve event ordering, sequence/gap checks, and data-quality diagnostics. Do not reconstruct historical L2 from candles.

### 2. Feature Layer

V9 will evaluate economically motivated microstructure state variables rather than simply add many correlated indicators. The initial candidate families are:

- multi-level order-flow imbalance with explicit level aggregation;
- queue imbalance and microprice displacement;
- aggressive trade-flow imbalance and persistence;
- large-trade direction/intensity;
- spread state and spread transitions;
- depth depletion/replenishment and book resiliency;
- liquidity concentration and depth slope;
- short-horizon volatility/event-rate state;
- interaction terms only where a documented microstructure mechanism justifies them.

Every feature must be timestamp-causal and generated without access to future events.

### 3. Target Layer

Define forward mid-price response at explicitly pre-registered horizons. Initial horizons are 100 ms, 250 ms, 500 ms, 1 s, 5 s, and 10 s for research characterization; the final trading horizon is selected only from pre-specified economic and statistical criteria, not by searching for the best historical result.

The primary target is forward mid-price return in basis points. Execution-aware targets will additionally measure attainable price movement relative to the modeled entry/exit mechanism.

### 4. Signal Layer

Separate prediction from trading decisions. A predictive model produces an expected forward return or probability distribution. A decision layer converts this prediction into LONG, SHORT, or NO_TRADE only when the expected economic value exceeds the contemporaneous execution-cost estimate with a statistical confidence margin.

No raw-sign trading rule will be treated as production-ready merely because its mean return is statistically non-zero.

### 5. Execution Layer

Use the repository's execution abstractions but remove the current research/production mismatch. Maker and taker paths must have explicit fee, spread, slippage, fill-probability, adverse-selection, latency, and partial-fill assumptions. The strategy must be evaluated under both optimistic and conservative execution scenarios.

### 6. Validation Layer

Use chronological train/validation/OOS partitions, walk-forward evaluation, session-level stability, bootstrap confidence intervals, permutation/placebo controls, and multiple-testing correction. The test protocol must be fixed before final model selection.

A strategy cannot pass solely because a pooled p-value is small. Economic magnitude, confidence interval, stability, and implementation feasibility are required together.

### 7. Deployment Layer

Paper trading remains the default. Live execution remains hard-locked until all research, economic, execution, reconciliation, and operational gates pass. The existing V5/V6 no-live governance must not be weakened merely to enable experimentation.

## Model Selection Policy

Prefer the simplest model that survives the complete validation protocol. Candidate models may include regularized linear models and other low-complexity probabilistic models where justified by sample size and calibration requirements. No deep model or large hyperparameter search will be introduced unless the simpler baseline demonstrates a robust incremental information gap worth investigating.

All parameters that affect model selection, signal generation, or execution must be pre-registered before OOS evaluation. OOS results cannot be used to tune the same candidate and then be reported as independent evidence.

## Economic Pass Gate

A candidate can be classified as deployable only if:

1. expected net return is positive after measured fees and realistic execution costs;
2. the lower confidence bound on net expectancy remains economically acceptable under the predefined statistical test;
3. the result survives chronological OOS and walk-forward evaluation;
4. performance is not concentrated in one session or one narrow market regime;
5. placebo/permutation controls reject the corresponding null behavior appropriately;
6. execution assumptions are supported by measured or conservatively bounded data;
7. data-quality, reconciliation, and risk controls pass independently.

If no candidate passes, the correct output is **NO_DEPLOYABLE_EDGE**, together with the highest-value missing-information or execution-data requirement. The project must not manufacture a positive result by relaxing gates after observing outcomes.

## Production Safety

V9 research code must remain isolated from the frozen V5/V6 production path until it has passed validation. No API key, live order, or production position action is permitted during research. Paper mode and deterministic replay are mandatory before any live authorization can be considered.

## Initial Deliverables

- V9 pre-registered research specification and hypothesis registry.
- V9 causal feature engine or extensions to existing feature infrastructure.
- V9 target/label construction with explicit horizon handling.
- V9 model and calibration pipeline.
- Execution-aware backtest/economic evaluator.
- Walk-forward/OOS validation and statistical report.
- Paper-trading integration using the existing safety architecture.
- Final V9 algorithm status report stating PASS or NO_DEPLOYABLE_EDGE with the complete audit trail.

## Research References

The design is grounded in established market-microstructure work already used by the project, including Cont, Kukanov & Stoikov on order-book events and price impact; Easley, López de Prado & O'Hara on flow toxicity; Chordia, Subrahmanyam & Roll on order imbalance and liquidity; Bouchaud, Farmer & Lillo on order-flow persistence; and Hasbrouck's work on market microstructure and price discovery. These references motivate hypotheses; they do not constitute evidence that a particular V9 implementation is profitable.

## Non-Goals

- No blind parameter optimization.
- No modification of historical V5/V6 results.
- No retrospective OOS tuning.
- No assumption that statistical significance implies economic significance.
- No live trading before the complete gate passes.
