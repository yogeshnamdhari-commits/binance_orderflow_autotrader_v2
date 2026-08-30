# V9 Cross-Asset Lead-Lag Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Build a research-only V9 pipeline that tests BTCUSDT lead-lag information against a fixed 10-altcoin Binance USDⓈ-M basket without altering frozen V5–V8 artifacts or the live-trading hard block.

**Architecture:** Add isolated V9 data validation, feature construction, baseline/treatment modeling, cost-aware evaluation, and walk-forward reporting. Reuse existing data-quality, cost-calibration, and validation conventions where compatible; do not route V9 signals into the V5 production decision engine until a separate deployment review passes.

**Tech Stack:** Existing Python project, pandas/pyarrow, existing test framework and repository cost/validation utilities.

**Spec:** `docs/V9_CROSS_ASSET_LEAD_LAG_DESIGN.md`

## Global Constraints

- V5–V8 research artifacts remain unchanged.
- V5 live-trading hard block remains enabled.
- Primary horizon is 5 minutes; secondary horizons are 10 and 15 minutes.
- Exactly 10 followers selected by a pre-specified historical-liquidity rule.
- Control model uses follower-only information; treatment adds causal BTC information.
- Execution costs are measured and instrument-specific.
- Final OOS observations cannot be used for parameter selection.
- Statistical significance alone cannot produce a deployable decision.

---

### Task 1: Repository and data inventory

**Files:**
- Create: `research/v9_data_inventory.py`
- Create: `tests/research/test_v9_data_inventory.py`

**Interfaces:**
- Inventory function reports candidate BTC/follower files, timestamp coverage, symbol coverage, sampling frequency, missingness and required fields.

- [ ] Write tests for missing required timestamp/price fields and coverage gaps.
- [ ] Run focused tests and verify failure before implementation.
- [ ] Implement inventory using existing repository conventions.
- [ ] Run focused tests and applicable research tests.
- [ ] Commit: `research: add V9 data inventory validation`

### Task 2: Historical-liquidity universe selector

**Files:**
- Create: `app/v9_universe.py`
- Create: `tests/test_v9_universe.py`

**Interfaces:**
- `select_v9_universe(liquidity_frame, asof, n=10) -> list[str]`
- Uses only liquidity observations available before `asof`.

- [ ] Write tests for deterministic selection, BTC exclusion, future-data exclusion and ties.
- [ ] Implement deterministic selection.
- [ ] Test fewer-than-10 eligible contracts as an explicit failure.
- [ ] Commit: `research: implement deterministic V9 follower universe`

### Task 3: Causal synchronized feature/label construction

**Files:**
- Create: `app/v9_features.py`
- Create: `tests/test_v9_features.py`

**Interfaces:**
- `build_v9_panel(btc, followers, horizons=(5, 10, 15)) -> pandas.DataFrame`
- Predictors are known at or before t; labels use strictly later prices.

- [ ] Write tests for no-lookahead, timestamp alignment, duplicates, missing data and forward-label boundaries.
- [ ] Implement causal synchronization and explicit missing-data policy.
- [ ] Record purge metadata for overlapping labels.
- [ ] Commit: `research: add causal V9 panel construction`

### Task 4: Control and treatment model fitting

**Files:**
- Create: `app/v9_models.py`
- Create: `tests/test_v9_models.py`

**Interfaces:**
- `fit_control(X_alt, y) -> fitted_model`
- `fit_treatment(X_alt_btc, y) -> fitted_model`
- `predict_probability(model, X) -> numpy.ndarray`

- [ ] Write tests for identical training rows, deterministic preprocessing and finite predictions.
- [ ] Implement regularized logistic regression with configuration fixed outside final OOS.
- [ ] Persist feature/model metadata for auditability.
- [ ] Commit: `research: add V9 control and treatment models`

### Task 5: Incremental predictive evaluation

**Files:**
- Create: `research/v9_evaluation.py`
- Create: `tests/research/test_v9_evaluation.py`

**Interfaces:**
- `evaluate_incremental(control_prob, treatment_prob, y) -> dict`
- Reports accuracy, log-loss, calibration diagnostics and incremental predictive metrics.

- [ ] Write tests for metric calculations and degenerate samples.
- [ ] Implement evaluation without OOS threshold selection.
- [ ] Apply a pre-declared multiple-testing correction across the fixed asset/horizon family.
- [ ] Commit: `research: add V9 incremental evaluation`

### Task 6: Instrument-specific economic evaluation

**Files:**
- Create: `app/v9_costs.py`
- Create: `tests/test_v9_costs.py`

**Interfaces:**
- `load_v9_costs(symbol, calibration) -> dict`
- `net_expectancy(gross_bps, costs) -> float`

- [ ] Write tests ensuring applicable fees, spread, slippage/impact and funding are incorporated.
- [ ] Implement measured-cost lookup with explicit failure when calibration is missing; never guess costs.
- [ ] Report gross and net separately.
- [ ] Commit: `research: add measured V9 economic gate`

### Task 7: Walk-forward and purged OOS runner

**Files:**
- Create: `research/v9_walkforward.py`
- Create: `tests/research/test_v9_walkforward.py`

**Interfaces:**
- `run_v9_walkforward(panel, splits, horizons) -> dict`
- Produces per-window, per-asset and aggregate OOS results.

- [ ] Write tests proving chronological ordering and purge gaps.
- [ ] Implement walk-forward evaluation.
- [ ] Persist split definitions and sample counts.
- [ ] Commit: `research: add V9 walk-forward validation`

### Task 8: V9 report and deployment separation

**Files:**
- Create: `research/V9_RESEARCH_REPORT.md`
- Create: `research/V9_DEPLOYMENT_GATE.md`
- Create: `tests/test_v9_governance.py`

**Interfaces:**
- Report consumes persisted V9 evaluation artifacts.
- Governance test proves V9 cannot bypass `V5_BASELINE_NO_LIVE_TRADE`.

- [ ] Write governance tests first.
- [ ] Generate reproducible report with data lineage, model definitions, OOS results, costs and uncertainty.
- [ ] Classify V9 as `DEPLOYABLE_EDGE`, `REJECTED`, or `BLOCKED` using pre-declared gates.
- [ ] Confirm no V9 path can execute live orders.
- [ ] Run V9 and relevant regression tests.
- [ ] Commit: `research: add V9 validation and deployment gate`

### Task 9: Final verification

- [ ] Inspect complete V9 diff.
- [ ] Run focused V9 tests.
- [ ] Run full applicable test suite.
- [ ] Verify V5–V8 files are unchanged.
- [ ] Verify live-trading hard block remains enabled.
- [ ] Scan final report for placeholders, leakage, unmeasured costs and post-OOS tuning.
- [ ] Only after verification, prepare a pull request for review.
