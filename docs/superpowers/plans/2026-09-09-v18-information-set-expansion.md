# V18 Information-Set Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a leakage-safe V18 research layer that adds liquidation, funding/basis and cross-market information to the frozen V16 order-flow control, then evaluates whether the added information improves net expectancy after execution costs.

**Architecture:** V18 is an additive research layer around the frozen V16 control. A timestamped feature assembler produces only as-of-available features; separate return, fill and execution-cost models feed an expected-net-P&L decision engine; validation compares V18 with V16 using identical chronological, purged splits and historical replay where genuine L2 exists.

**Tech Stack:** Python, existing repository data structures, NumPy/Pandas/scikit-learn dependencies already present in the repository, JSON evidence artifacts, pytest.

**Spec:** `docs/superpowers/specs/2026-09-09-v18-information-set-expansion-design.md`

## Global Constraints

- V16 remains the frozen control group.
- V17 is not a production candidate and is not allowed to replace V16 as the control.
- `LIVE_ORDER_SUBMISSION` remains hard-disabled throughout V18 research.
- All feature joins use event/availability timestamps and must be leakage-safe.
- Historical L2 must be genuine exchange depth data, never reconstructed from candles.
- Prediction horizon, model family, feature families and economic gates are pre-registered before outcome inspection.
- Net EV after execution costs is the primary economic criterion.
- No threshold, horizon, feature, or cost parameter may be changed after observing V18 results to obtain a pass.
- Every reported result must be reproducible from saved data/configuration/evidence artifacts.

---

### Task 1: V18 frozen research configuration

**Files:**
- Create: `app/v18/__init__.py`
- Create: `app/v18/config.py`
- Create: `data/research/v18_proposal.json`
- Test: `tests/v18/test_config.py`

**Interfaces:**
- `V18Config` is an immutable configuration object containing symbol, prediction horizon, feature-family switches, minimum sample requirements, walk-forward parameters, cost-stress multipliers and safety flags.
- `load_v18_config(path: Path) -> V18Config` loads and validates the pre-registered configuration.

- [ ] **Step 1: Write failing configuration tests**

Test that the configuration rejects missing prediction horizon, unknown feature families, non-positive sample thresholds and any configuration that enables live order submission.

- [ ] **Step 2: Run the focused tests**

Run: `pytest tests/v18/test_config.py -v`
Expected: FAIL before implementation.

- [ ] **Step 3: Implement the immutable configuration and JSON loader**

The loader must validate the schema and expose a deterministic configuration hash used by every V18 evidence artifact.

- [ ] **Step 4: Run focused tests again**

Run: `pytest tests/v18/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/v18 tests/v18 data/research/v18_proposal.json
git commit -m "research: preregister V18 configuration"
```

### Task 2: Timestamp-safe information-set assembler

**Files:**
- Create: `app/v18/information_set.py`
- Create: `app/v18/synchronization.py`
- Test: `tests/v18/test_information_set.py`

**Interfaces:**
- `MarketObservation(timestamp_ns: int, source: str, values: Mapping[str, float])` represents one timestamped observation.
- `asof_join(target_times: Sequence[int], observations: Sequence[MarketObservation], max_age_ns: int) -> list[dict[str, float | int | None]]` performs backward-only joins.
- `assemble_information_set(event, book_features, trade_features, liquidation, funding, cross_market) -> dict[str, float]` emits the feature vector available at the event timestamp.

- [ ] **Step 1: Write failing leakage tests**

Include a future observation, an out-of-order observation, a duplicate timestamp and a stale observation. Assert that future values are never selected, duplicates are deterministically resolved, and stale data is marked missing rather than forward-filled indefinitely.

- [ ] **Step 2: Run focused tests**

Run: `pytest tests/v18/test_information_set.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement backward-only timestamp joins and data-quality flags**

Preserve source timestamp, availability timestamp, age and missingness for each external information family.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/v18/test_information_set.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/v18/information_set.py app/v18/synchronization.py tests/v18/test_information_set.py
git commit -m "research: add leakage-safe V18 information set"
```

### Task 3: Liquidation, funding/basis and cross-market feature families

**Files:**
- Create: `app/v18/features.py`
- Create: `app/v18/external_data.py`
- Test: `tests/v18/test_features.py`

**Interfaces:**
- `compute_liquidation_features(events, now_ns, windows_ns) -> dict[str, float]` returns signed liquidation intensity, imbalance and recency features.
- `compute_funding_basis_features(observations, now_ns) -> dict[str, float]` returns funding state, mark/index premium and basis features with age flags.
- `compute_cross_market_features(target_event, spot, perpetual, reference_markets) -> dict[str, float]` returns lagged relative-return, spread and confirmation/divergence features.

- [ ] **Step 1: Write failing feature tests**

Use synthetic event streams with known signed flow and timestamps. Verify exact feature values, no future use, normalization against only prior observations, and stable behavior under missing data.

- [ ] **Step 2: Run focused tests**

Run: `pytest tests/v18/test_features.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement minimal deterministic feature functions**

Keep the first implementation low-dimensional and economically interpretable. Do not introduce deep learning or dozens of correlated variants.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/v18/test_features.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/v18/features.py app/v18/external_data.py tests/v18/test_features.py
git commit -m "research: add V18 external information features"
```

### Task 4: Return, fill and execution models

**Files:**
- Create: `app/v18/models.py`
- Create: `app/v18/execution.py`
- Test: `tests/v18/test_models.py`

**Interfaces:**
- `fit_return_model(X, y, config) -> ReturnModel` estimates conditional signed return magnitude.
- `fit_fill_model(X, filled, config) -> FillModel` estimates execution probability.
- `expected_net_pnl(return_model, fill_model, execution_model, features) -> float` computes expected net P&L from the same event-level definitions used in validation.

- [ ] **Step 1: Write failing accounting tests**

Test that gross return, fill probability, maker/taker cost, non-fill opportunity cost and realized simulated P&L reconcile at the trade level.

- [ ] **Step 2: Run focused tests**

Run: `pytest tests/v18/test_models.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement baseline regularized models and explicit accounting**

Use a simple regularized model as the primary baseline. Keep model fitting strictly inside each training fold. Never fit preprocessing, calibration or feature normalization on future data.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/v18/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/v18/models.py app/v18/execution.py tests/v18/test_models.py
git commit -m "research: add V18 return fill and execution models"
```

### Task 5: V16-vs-V18 walk-forward evaluator

**Files:**
- Create: `app/v18/walk_forward.py`
- Create: `app/v18/evaluate.py`
- Test: `tests/v18/test_walk_forward.py`

**Interfaces:**
- `make_purged_splits(events, train_size, test_size, embargo) -> list[Split]` creates chronological non-overlapping folds.
- `evaluate_control_and_candidate(v16_model, v18_model, events, splits, costs) -> EvaluationResult` evaluates both systems on the same test events.
- `apply_multiple_testing_control(results, alpha) -> AdjustedResults` applies the repository's established false-discovery control to the pre-registered hypothesis families.

- [ ] **Step 1: Write failing split and leakage tests**

Verify chronological ordering, no train/test overlap, purge/embargo behavior, identical candidate/control test events and fold-local fitting.

- [ ] **Step 2: Run focused tests**

Run: `pytest tests/v18/test_walk_forward.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement evaluator using existing repository validation conventions**

Report net EV, realized simulated P&L, confidence intervals, p-values, trade count, positive-fold count and effect relative to V16.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/v18/test_walk_forward.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/v18/walk_forward.py app/v18/evaluate.py tests/v18/test_walk_forward.py
git commit -m "research: add V18 walk-forward evaluator"
```

### Task 6: Historical L2 replay and robustness gates

**Files:**
- Create: `app/v18/replay.py`
- Create: `app/v18/robustness.py`
- Test: `tests/v18/test_replay.py`
- Test: `tests/v18/test_robustness.py`

**Interfaces:**
- `run_historical_replay(dataset, model, config) -> ReplayResult` replays genuine L2 events without reconstructing depth from candles.
- `run_robustness_suite(result, stress_multipliers, regime_blocks) -> RobustnessResult` runs chronological blocks, cost stress and leave-one-regime-out analysis.

- [ ] **Step 1: Write failing replay/accounting tests**

Verify event ordering, no duplicate execution, correct fill/cost accounting and preservation of the original event timestamps.

- [ ] **Step 2: Run focused tests**

Run: `pytest tests/v18/test_replay.py tests/v18/test_robustness.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement replay and robustness gates**

A positive result must survive the configured cost stress and leave-one-regime-out requirements. Any missing or synthetic L2 input must fail the historical replay gate rather than being silently substituted.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/v18/test_replay.py tests/v18/test_robustness.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/v18/replay.py app/v18/robustness.py tests/v18/test_replay.py tests/v18/test_robustness.py
git commit -m "research: add V18 replay and robustness gates"
```

### Task 7: V18 research runner and evidence artifacts

**Files:**
- Create: `app/v18/research_runner.py`
- Create: `tests/v18/test_research_runner.py`
- Create: `data/evidence/v18/README.md`

**Interfaces:**
- `run_v18_research(config_path: Path) -> Path` executes the pre-registered pipeline and writes an immutable evidence manifest.

- [ ] **Step 1: Write failing runner tests**

Verify that the runner refuses to execute with a missing configuration hash, refuses live submission, and records input hashes, code revision, model configuration and output metrics.

- [ ] **Step 2: Run focused tests**

Run: `pytest tests/v18/test_research_runner.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement the runner and evidence manifest**

Evidence must distinguish model-predicted expectancy from realized simulated P&L and must include the V16 comparator.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/v18/test_research_runner.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/v18/research_runner.py tests/v18/test_research_runner.py data/evidence/v18/README.md
git commit -m "research: add V18 reproducible runner"
```

### Task 8: Full verification and economic decision

**Files:**
- Modify: `FINAL_STATUS.json`
- Create: `data/evidence/v18/v18_final_report.json`
- Create: `data/evidence/v18/v18_final_report.md`
- Test: full repository test suite

- [ ] **Step 1: Run all V18 tests**

Run: `pytest tests/v18 -v`
Expected: PASS with zero V18 failures.

- [ ] **Step 2: Run the complete existing test suite**

Run: `pytest -q`
Expected: PASS except only documented pre-existing failures; no new regressions may be introduced.

- [ ] **Step 3: Run the V18 research pipeline on the pre-registered data**

Run: `python -m app.v18.research_runner data/research/v18_proposal.json`
Expected: reproducible evidence artifacts and an explicit PASS/FAIL economic decision.

- [ ] **Step 4: Apply the decision rule without tuning**

If V18 does not improve net EV over V16 with robustness gates intact, mark V18 as rejected and retain V16 as the control. If V18 improves net EV, freeze the resulting model/configuration and move only to the separately defined forward/paper gates; do not enable live submission.

- [ ] **Step 5: Commit evidence and final status**

```bash
git add FINAL_STATUS.json data/evidence/v18
git commit -m "research: record V18 economic evaluation"
```
