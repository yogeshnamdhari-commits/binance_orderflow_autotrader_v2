# V19 Economic Order-Flow Correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and evaluate a compact, causally safe V19 order-flow candidate whose decision criterion is realistic expected net P&L and whose production candidacy is determined only by independent forward and historical-L2 evidence.

**Architecture:** V19 is a new research namespace copied conceptually from the modular V18 structure but does not mutate V16. It contains a compact feature extractor, separate return/fill models, explicit execution economics, purged walk-forward evaluation, and a production gate that compares V19 against the frozen V16 control. V18's liquidation/funding/cross-market expansion is excluded from the primary V19 model and can only appear in explicitly logged ablations.

**Tech Stack:** Python 3, NumPy, scikit-learn, pytest, JSON evidence artifacts, existing Binance L2 replay interfaces.

**Spec:** `docs/superpowers/specs/2026-09-09-v19-economic-orderflow-design.md`

## Global Constraints

- `LIVE_ORDER_SUBMISSION` stays hard-disabled for every V19 configuration and test.
- V16 remains frozen and is never edited by V19 work.
- Feature transforms and model fitting use only observations available before the prediction timestamp.
- All model selection is performed on chronological training/validation data; the final historical replay remains unseen until the locked evaluation stage.
- Net EV, not AUC or gross EV, is the primary economic metric.
- No arbitrary parameter search; every retained parameter is declared in configuration and justified by microstructure or execution logic.
- A negative V19 result is a valid research outcome; the gate must reject V19 rather than tune until it passes.

---

### Task 1: Establish V19 research contract and frozen-control comparator

**Files:**
- Create: `app/v19/__init__.py`
- Create: `app/v19/config.py`
- Create: `app/v19/comparison.py`
- Create: `tests/v19/test_config.py`
- Create: `tests/v19/test_comparison.py`

**Interfaces:**
- `V19Config` contains `symbol`, `prediction_horizon_ms`, `feature_names`, `min_train_events`, `min_test_events`, `embargo_events`, `max_feature_age_ms`, `maker_round_trip_cost_bps`, `taker_round_trip_cost_bps`, `non_fill_opportunity_cost_bps`, `maker_share`, `cost_stress_multipliers`, and `live_order_submission`.
- `load_v19_config(path: Path) -> V19Config` validates the immutable research contract and rejects live order submission.
- `compare_to_v16(v19: Sequence[float], v16: Sequence[float]) -> dict[str, float]` returns paired incremental mean, bootstrap confidence interval, and sign-test p-value for aligned trade/event outcomes.

- [ ] **Step 1: Write failing configuration tests**

```python
def test_v19_rejects_live_submission(tmp_path):
    path = tmp_path / "v19.json"
    path.write_text('{"symbol":"BTCUSDT","prediction_horizon_ms":2000,"feature_names":["ofi_1"],"min_train_events":100,"min_test_events":50,"embargo_events":2,"max_feature_age_ms":1000,"maker_round_trip_cost_bps":1.0,"taker_round_trip_cost_bps":2.0,"non_fill_opportunity_cost_bps":0.5,"maker_share":1.0,"cost_stress_multipliers":[1.0,1.25],"live_order_submission":true}')
    with pytest.raises(ValueError, match="live order submission"):
        load_v19_config(path)
```

- [ ] **Step 2: Run the targeted test and verify the missing V19 module causes failure**

Run: `pytest tests/v19/test_config.py -q`
Expected: collection/import failure because `app.v19.config` does not yet exist.

- [ ] **Step 3: Implement immutable config validation and V16 comparator**

Use dataclasses and canonical JSON hashing, mirroring the existing research-config pattern, but expose only the V19 fields listed above. `live_order_submission=True` must raise immediately. `compare_to_v16` must reject unequal aligned lengths and compute paired differences without looking at future observations.

- [ ] **Step 4: Run targeted tests**

Run: `pytest tests/v19/test_config.py tests/v19/test_comparison.py -q`
Expected: all V19 contract tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/v19 tests/v19
git commit -m "research: establish V19 economic contract"
```

---

### Task 2: Implement compact causal order-flow feature layer

**Files:**
- Create: `app/v19/features.py`
- Create: `tests/v19/test_features.py`

**Interfaces:**
- `L2Event` stores `timestamp_ns`, `bid_px`, `bid_qty`, `ask_px`, `ask_qty`, `trade_side`, and `trade_qty`.
- `compute_orderflow_features(events: Sequence[L2Event], now_ns: int, levels: int = 3, window_ns: int = 2_000_000_000) -> dict[str, float]` returns only past-information features.
- Required features: top-level and multi-level queue imbalance, OFI, signed trade flow, spread in bps, depth concentration, queue-change intensity, and short-window liquidity state.
- `feature_names() -> tuple[str, ...]` returns deterministic ordering.

- [ ] **Step 1: Write leakage-focused failing tests**

```python
def test_future_event_cannot_change_features():
    past = [L2Event(1, 100, 10, 101, 8, "BUY", 2)]
    future = L2Event(3, 100, 1000, 101, 1, "SELL", 999)
    a = compute_orderflow_features(past, 2)
    b = compute_orderflow_features(past + [future], 2)
    assert a == b
```

- [ ] **Step 2: Run the test and verify failure**

Run: `pytest tests/v19/test_features.py::test_future_event_cannot_change_features -q`
Expected: failure because the V19 feature layer does not exist.

- [ ] **Step 3: Implement causal feature extraction**

Filter `timestamp_ns <= now_ns` before every aggregation. Normalize queue imbalance by total visible quantity. Compute OFI from signed changes in bid/ask queue state, signed trade flow from trades already observed, spread from current best quotes, and depth concentration from the first `levels` levels. Reject non-positive prices/quantities and return deterministic finite floats.

- [ ] **Step 4: Add invariance tests**

Test that event reordering is rejected or normalized, zero-depth produces finite neutral values, and changing only future events leaves every feature unchanged.

- [ ] **Step 5: Run feature tests**

Run: `pytest tests/v19/test_features.py -q`
Expected: all feature and leakage tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/v19/features.py tests/v19/test_features.py
git commit -m "research: add causal compact order-flow features"
```

---

### Task 3: Separate return, fill, and execution economics

**Files:**
- Create: `app/v19/models.py`
- Create: `app/v19/execution.py`
- Create: `tests/v19/test_models.py`
- Create: `tests/v19/test_execution.py`

**Interfaces:**
- `fit_return_model(X: np.ndarray, y: Sequence[float], feature_names: Sequence[str]) -> ReturnModel` uses a regularized linear estimator with training-only scaling.
- `fit_fill_model(X: np.ndarray, filled: Sequence[int], feature_names: Sequence[str]) -> FillModel` returns calibrated fill probabilities.
- `expected_net_pnl(predicted_return_bps: float, fill_probability: float, maker_round_trip_cost_bps: float, taker_round_trip_cost_bps: float, non_fill_opportunity_cost_bps: float, maker_share: float) -> float` computes expected net P&L.
- `simulate_realized_fill(predicted_return_bps: float, filled: bool, maker: bool, maker_cost_bps: float, taker_cost_bps: float) -> float` computes realized trade outcome.

- [ ] **Step 1: Write failing economic-accounting tests**

```python
def test_non_fill_cost_is_conditional():
    assert expected_net_pnl(4.0, 0.5, 1.0, 2.0, 0.8, 1.0) == pytest.approx(0.6)

def test_realized_non_fill_has_no_execution_cost():
    assert simulate_realized_fill(4.0, False, True, 1.0, 2.0) == pytest.approx(0.0)
```

- [ ] **Step 2: Run targeted tests and verify failure**

Run: `pytest tests/v19/test_models.py tests/v19/test_execution.py -q`
Expected: import failure until V19 implementations exist.

- [ ] **Step 3: Implement regularized models**

Use `StandardScaler` + `Ridge` for return and `StandardScaler` + `LogisticRegression` for fill, matching the repository's existing dependency set. Fit each model only on the supplied training slice. Expose feature names so prediction-time column order is checked.

- [ ] **Step 4: Implement exact net-P&L accounting**

For a passive order, expected net P&L is `fill_probability * (predicted_return - maker_cost) - (1-fill_probability) * non_fill_opportunity_cost`. For an aggressive order, use taker cost. Never subtract execution cost from an unfilled order. Return values must be finite and inputs must be range-checked.

- [ ] **Step 5: Run targeted tests**

Run: `pytest tests/v19/test_models.py tests/v19/test_execution.py -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/v19/models.py app/v19/execution.py tests/v19/test_models.py tests/v19/test_execution.py
git commit -m "research: separate return fill and execution economics"
```

---

### Task 4: Build locked chronological evaluation and robustness gate

**Files:**
- Create: `app/v19/walk_forward.py`
- Create: `app/v19/gate.py`
- Create: `app/v19/pipeline.py`
- Create: `tests/v19/test_walk_forward.py`
- Create: `tests/v19/test_gate.py`

**Interfaces:**
- `make_purged_splits(timestamps_ns: Sequence[int], train_size: int, test_size: int, embargo_events: int) -> list[Split]` creates expanding chronological splits.
- `evaluate_fold(features, returns, fills, timestamps_ns, split, config) -> FoldResult` fits on train only and produces test predictions and realized outcomes.
- `run_cost_stress(results, multipliers) -> dict[float, float]` recomputes net EV under each declared cost multiplier without refitting.
- `evaluate_gate(v19_results, v16_results, robustness, config) -> GateResult` returns pass/fail plus explicit rejection reasons.

- [ ] **Step 1: Write failing purge/embargo tests**

```python
def test_embargo_separates_train_and_test():
    splits = make_purged_splits(list(range(20)), 8, 4, 2)
    assert max(splits[0].train) < min(splits[0].test) - 1
```

- [ ] **Step 2: Run targeted test and verify failure**

Run: `pytest tests/v19/test_walk_forward.py -q`
Expected: import failure before implementation.

- [ ] **Step 3: Implement chronological split and fold evaluation**

Reuse the proven split semantics from `app/v18/walk_forward.py`, but ensure the prediction horizon is covered by the embargo. Fit transforms/models inside each fold and emit fold-level predictions, fill probabilities, realized P&L, and event timestamps.

- [ ] **Step 4: Implement robustness metrics**

Compute overall net EV, realized net EV, confidence interval, chronological block means, leave-one-regime-out results, and cost-stress results. A gate failure must identify the exact failed criterion.

- [ ] **Step 5: Implement V19-vs-V16 economic gate**

Require positive incremental net EV, confidence interval excluding zero, no negative chronological block, and survival of the configured cost stress. Historical replay is evaluated separately and must remain locked until the forward gate is frozen.

- [ ] **Step 6: Run targeted tests**

Run: `pytest tests/v19/test_walk_forward.py tests/v19/test_gate.py -q`
Expected: all evaluation/gate tests pass.

- [ ] **Step 7: Commit**

```bash
git add app/v19/walk_forward.py app/v19/gate.py app/v19/pipeline.py tests/v19/test_walk_forward.py tests/v19/test_gate.py
git commit -m "research: add locked V19 validation and robustness gate"
```

---

### Task 5: Integrate replay, evidence generation, and production lock

**Files:**
- Create: `app/v19/replay.py`
- Create: `app/v19/run.py`
- Create: `tests/v19/test_replay.py`
- Create: `tests/v19/test_run.py`
- Create: `data/evidence/v19/` JSON outputs generated by the runner
- Modify: repository research documentation only if the existing gate entry point requires a V19 reference

**Interfaces:**
- `run_forward_validation(config_path: Path) -> Path` writes immutable forward evidence.
- `run_historical_replay(config_path: Path, replay_path: Path) -> Path` evaluates the frozen candidate on unseen L2 replay.
- `write_production_gate(result: GateResult, path: Path) -> None` writes an explicit gate record with `live_order_submission: false`.

- [ ] **Step 1: Write failing replay isolation test**

```python
def test_replay_requires_frozen_candidate(tmp_path):
    with pytest.raises(ValueError, match="frozen"):
        run_historical_replay(tmp_path / "unfrozen.json", tmp_path / "replay")
```

- [ ] **Step 2: Run targeted test and verify failure**

Run: `pytest tests/v19/test_replay.py tests/v19/test_run.py -q`
Expected: import failure before implementation.

- [ ] **Step 3: Connect the existing Binance L2 replay interface**

Locate the existing historical replay loader and adapt it through a narrow V19 adapter rather than duplicating the data parser. Feed only timestamps/features that were available at each decision event. Do not synthesize L2 from candles.

- [ ] **Step 4: Generate locked evidence artifacts**

Write JSON records containing config hash, source dataset identifiers/checksums, feature list, split definitions, model specification, cost assumptions, forward metrics, historical replay metrics, robustness metrics, V16 comparator metrics, and gate decision. Include `live_order_submission=false` in every evidence record.

- [ ] **Step 5: Add end-to-end tests**

Run: `pytest tests/v19 -q`
Expected: all V19 tests pass with zero failures.

- [ ] **Step 6: Commit**

```bash
git add app/v19 tests/v19 data/evidence/v19
 git commit -m "research: integrate V19 replay and evidence gate"
```

---

### Task 6: Full verification and research decision

**Files:**
- Review: all `app/v19/**`, `tests/v19/**`, and generated evidence.
- Create: `data/evidence/v19/final_report.md`

- [ ] **Step 1: Run the complete repository test suite**

Run: `pytest -q`
Expected: zero new failures; record the exact count of passed/failed/skipped tests.

- [ ] **Step 2: Run V19 forward validation**

Run the repository's V19 runner against the frozen forward dataset. Record net EV, realized net EV, confidence interval, p-value, number of trades/events, and every robustness gate.

- [ ] **Step 3: Freeze forward decisions before historical replay**

Persist the forward configuration hash and model-selection manifest. No model/feature/config changes are permitted after this point before replay.

- [ ] **Step 4: Run unseen historical L2 replay**

Execute the locked replay using the authentic L2 dataset. Record net EV and realized net EV, confidence interval, regime results, and cost stress.

- [ ] **Step 5: Compare V19 against V16**

Compute incremental economic performance on both forward and historical replay. Do not use AUC as the acceptance metric.

- [ ] **Step 6: Write the final research decision**

If every acceptance criterion passes, mark V19 as the research production candidate while keeping live submission disabled pending the separate authorization procedure. If any criterion fails, mark V19 `REJECTED`, retain V16 as the control, and document the exact failure without tuning around it.

- [ ] **Step 7: Verify repository state and CI evidence before claiming completion**

Run the complete tests again after the final evidence write. Inspect the final diff and the generated gate record. Only report success claims supported by these fresh outputs.

- [ ] **Step 8: Commit the final evidence**

```bash
git add data/evidence/v19/final_report.md data/evidence/v19
git commit -m "research: record V19 economic validation decision"
```
