# Autonomous Order-Flow V15 Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the existing Binance BTCUSDT order-flow project into a deterministic replay/paper/testnet-ready autonomous trading pipeline with causal features, frozen-model governance, realistic cost/risk gates, order reconciliation, and fail-closed production controls.

**Architecture:** Add a focused `app/v15/` runtime layer over the existing feed, book, feature, decision, cost, and execution primitives rather than replacing the validated V5/V12/V13/V14 history. The V15 layer uses one event/decision/execution interface across replay, paper, and testnet, while live order submission remains hard-disabled until independent economic validation and explicit authorization pass.

**Tech Stack:** Python 3, pytest, existing project modules, Binance WebSocket/REST adapters, JSON/JSONL evidence artifacts, existing virtual-environment dependency set.

**Spec:** `docs/superpowers/specs/2026-09-07-autonomous-orderflow-completion-design.md`

## Global Constraints

- Authentic Binance depth + trade data only; no synthetic historical L2 presented as real data.
- All features must be causal and timestamped by information availability.
- Model parameters are frozen during inference and verified by checksum/hash.
- No forward/test-set tuning or parameter fishing.
- A failed validation gate blocks promotion instead of triggering hidden retuning.
- Execution economics must include fees, spread, slippage, adverse selection, latency/queue uncertainty, and partial-fill effects where measurable.
- Replay, paper, testnet, and live use the same decision/risk/execution contracts.
- Data, model, configuration, and evidence failures are fail-closed.
- `LIVE_ORDER_SUBMISSION` remains hard-disabled until explicit production authorization after all required gates pass.
- Existing tests and pre-existing failures must not be hidden or reclassified as regressions without evidence.

---

## File/Module Map

The implementation will keep responsibilities narrow:

- `app/v15/types.py` — immutable event, book snapshot, feature snapshot, signal, order-intent, fill, and runtime-state contracts.
- `app/v15/book.py` — deterministic local L2 book reconstruction, sequence validation, stale/gap state, and snapshot recovery contract.
- `app/v15/features.py` — causal microstructure feature extraction from book/trade state; no future-looking values.
- `app/v15/model.py` — frozen model artifact loading, checksum verification, schema verification, and prediction/calibration interface.
- `app/v15/economics.py` — fee/spread/slippage/adverse-selection/latency cost model and expected-net-edge gate.
- `app/v15/risk.py` — exposure, order-size, loss, stale-data, spread, connectivity, and kill-switch rules.
- `app/v15/execution.py` — common execution adapter protocol plus replay/paper/testnet implementations and explicit live-lock guard.
- `app/v15/runtime.py` — event loop/orchestrator joining feed → book → features → model → economics → risk → execution → journal.
- `app/v15/evidence.py` — machine-readable run/evidence records and deterministic final status generation.
- `app/v15/__init__.py` — package boundary.
- `tests/v15/test_book.py`, `test_features.py`, `test_model.py`, `test_economics.py`, `test_risk.py`, `test_execution.py`, `test_runtime.py`, `test_evidence.py` — focused unit/integration coverage.
- `scripts/v15_replay.py` — deterministic offline runner over captured JSONL data.
- `scripts/v15_paper.py` — paper runtime entry point using the live feed but never submitting orders.
- `scripts/v15_testnet.py` — testnet entry point requiring explicit credentials and retaining all safety gates.
- `data/evidence/v15/` — generated evidence only; never used as calibration input unless explicitly part of a pre-registered development split.

---

### Task 1: Establish V15 contracts and baseline tests

**Files:**
- Create: `app/v15/__init__.py`
- Create: `app/v15/types.py`
- Create: `tests/v15/__init__.py`
- Create: `tests/v15/test_types.py`
- Modify: `app/config.py` only if the existing configuration has no safe way to expose a V15 mode; preserve existing defaults.

**Interfaces:**
- Produce `MarketEvent(kind: str, ts_ms: int, recv_ms: int, payload: dict, sequence: int | None)`.
- Produce `FeatureSnapshot(ts_ms: int, values: dict[str, float], source_sequence: int | None)`.
- Produce `Signal(direction: str, score: float, expected_gross_bps: float, model_hash: str)`.
- Produce `OrderIntent(side: str, quantity: float, order_type: str, limit_price: float | None, client_id: str)`.
- Produce `Fill(order_id: str, side: str, quantity: float, price: float, fee_bps: float, ts_ms: int)`.
- Produce `RuntimeState` with explicit states `STARTING`, `READY`, `NO_TRADE`, `ORDER_WORKING`, `RECONCILING`, `HALTED`.

- [ ] **Step 1: Write failing contract tests** covering valid construction, required fields, immutable semantics, and rejection of invalid directions/order sides.
- [ ] **Step 2: Run `pytest tests/v15/test_types.py -q` and confirm the new types are absent/failing.**
- [ ] **Step 3: Implement the typed dataclasses/enums with finite-number validation and explicit state values.**
- [ ] **Step 4: Run the focused test file and then `pytest tests/test_core.py -q`.**
- [ ] **Step 5: Commit `feat: add V15 runtime contracts`.**

---

### Task 2: Deterministic local order-book and data-integrity layer

**Files:**
- Create: `app/v15/book.py`
- Create: `tests/v15/test_book.py`
- Modify: `app/binance_feed.py` only where a small adapter is needed to convert existing feed events into `MarketEvent`.
- Test: `tests/test_feed_sync.py` remains authoritative for legacy behavior.

**Interfaces:**
- `OrderBook.apply_snapshot(bids, asks, last_update_id) -> None`.
- `OrderBook.apply_delta(event: MarketEvent) -> None`.
- `OrderBook.is_ready() -> bool`.
- `OrderBook.is_stale(now_ms, max_age_ms) -> bool`.
- `OrderBook.consume_gap() -> bool` returning true only when a sequence discontinuity is detected.
- `OrderBook.top_levels(n) -> tuple[list[tuple[float,float]], list[tuple[float,float]]]`.
- `OrderBook.mid_price() -> float` and `spread_bps() -> float`.

- [ ] **Step 1: Write tests for contiguous updates, crossed-book rejection, duplicate events, sequence gaps, stale state, and snapshot reset.**
- [ ] **Step 2: Run `pytest tests/v15/test_book.py -q` and confirm failures.**
- [ ] **Step 3: Implement deterministic sorted bid/ask maps, sequence tracking, and explicit invalid/stale states.**
- [ ] **Step 4: Add the existing Binance feed adapter without changing legacy feed semantics.**
- [ ] **Step 5: Run `pytest tests/v15/test_book.py tests/test_feed_sync.py -q`.**
- [ ] **Step 6: Commit `feat: add deterministic V15 order book`.**

---

### Task 3: Causal order-flow feature pipeline

**Files:**
- Create: `app/v15/features.py`
- Create: `tests/v15/test_features.py`
- Modify: none of the archived V5/V12/V13 feature definitions; V15 is a new experiment.

**Interfaces:**
- `FeatureEngine.update(event: MarketEvent, book: OrderBook) -> FeatureSnapshot | None`.
- `FeatureEngine.feature_names() -> tuple[str, ...]`.
- `FeatureEngine.reset() -> None`.

Feature families must be restricted to information available at `event.ts_ms`: L1/L5/L10 depth imbalance, OFI, trade imbalance/Delta, CVD, microprice deviation, spread, liquidity/depth, event rate, volatility, and explicitly versioned persistence/microstructure state. Every rolling feature must use only observations with timestamps <= the current event timestamp.

- [ ] **Step 1: Write failing tests that append a future event and prove the feature at time T is unchanged.**
- [ ] **Step 2: Add tests for deterministic replay, zero-depth handling, spread validity, and finite outputs.**
- [ ] **Step 3: Run `pytest tests/v15/test_features.py -q` and verify failure.**
- [ ] **Step 4: Implement the minimal causal feature engine using the V15 book state and bounded deques for rolling statistics.**
- [ ] **Step 5: Add feature-schema/version metadata to every snapshot.**
- [ ] **Step 6: Run `pytest tests/v15/test_features.py tests/test_features.py tests/test_feature_parity.py -q`.**
- [ ] **Step 7: Commit `feat: add causal V15 order-flow features`.**

---

### Task 4: Frozen model and economic decision gate

**Files:**
- Create: `app/v15/model.py`
- Create: `app/v15/economics.py`
- Create: `tests/v15/test_model.py`
- Create: `tests/v15/test_economics.py`
- Modify: `app/decision.py` only if a compatibility adapter is required; do not change the archived V5 behavior.

**Interfaces:**
- `FrozenModel.load(path: str, expected_sha256: str) -> FrozenModel`.
- `FrozenModel.predict(features: FeatureSnapshot) -> Signal`.
- `FrozenModel.metadata() -> dict`.
- `CostModel.expected_cost_bps(side, quantity, book, market_state) -> float`.
- `EconomicGate.evaluate(signal: Signal, expected_cost_bps: float, uncertainty_bps: float) -> str` returning `COST_OVERWHELMED`, `NO_SIGNAL`, or `EXECUTION_READY`.

- [ ] **Step 1: Write failing checksum, feature-schema, non-finite prediction, and frozen-artifact tests.**
- [ ] **Step 2: Write economic tests proving positive statistical score is rejected when expected costs overwhelm the edge and accepted only when the configured net-edge criterion is satisfied.**
- [ ] **Step 3: Run the focused tests and confirm failure.**
- [ ] **Step 4: Implement immutable artifact loading with SHA-256 verification and exact feature-name/order matching.**
- [ ] **Step 5: Implement cost aggregation for fee, spread, slippage, adverse selection, latency/queue allowance, and conservative uncertainty.**
- [ ] **Step 6: Implement the fail-closed economic gate with no hidden threshold optimization.**
- [ ] **Step 7: Run `pytest tests/v15/test_model.py tests/v15/test_economics.py tests/test_cost_calibration.py tests/test_decision.py -q`.**
- [ ] **Step 8: Commit `feat: add frozen model and economic gate`.**

---

### Task 5: Risk engine and common execution adapters

**Files:**
- Create: `app/v15/risk.py`
- Create: `app/v15/execution.py`
- Create: `tests/v15/test_risk.py`
- Create: `tests/v15/test_execution.py`

**Interfaces:**
- `RiskEngine.check(intent, account_state, market_state) -> tuple[bool, str]`.
- `RiskEngine.record_fill(fill) -> None`.
- `RiskEngine.halt(reason) -> None`.
- `ExecutionAdapter.submit(intent) -> str`.
- `ExecutionAdapter.cancel(order_id) -> None`.
- `ExecutionAdapter.reconcile() -> list[Fill]`.
- `ReplayExecution`, `PaperExecution`, `TestnetExecution`, and `LiveExecutionGuarded` implement the same interface.

`LiveExecutionGuarded.submit()` must raise a dedicated `LiveTradingLockedError` unless a separately verified production authorization artifact exists and all runtime gates are green. No environment variable alone can unlock live trading.

- [ ] **Step 1: Write failing tests for max position, max order size, loss limit, stale feed, wide spread, duplicate client IDs, cancel/reconcile, partial fills, and hard live lock.**
- [ ] **Step 2: Run `pytest tests/v15/test_risk.py tests/v15/test_execution.py -q` and verify failure.**
- [ ] **Step 3: Implement risk checks as deterministic pure decisions with explicit halt transitions.**
- [ ] **Step 4: Implement replay and paper adapters first; replay fills must be deterministic and paper must never call an exchange order endpoint.**
- [ ] **Step 5: Implement testnet adapter behind explicit credential presence and endpoint configuration.**
- [ ] **Step 6: Implement the live guard with a hard-coded false-by-default production submission flag and authorization-artifact verification.**
- [ ] **Step 7: Add idempotent client IDs, acknowledgement/rejection handling, partial-fill accounting, timeout cancellation, and reconciliation.**
- [ ] **Step 8: Run `pytest tests/v15/test_risk.py tests/v15/test_execution.py tests/test_execution.py tests/test_hardening.py -q`.**
- [ ] **Step 9: Commit `feat: add V15 risk and execution adapters`.**

---

### Task 6: End-to-end autonomous runtime

**Files:**
- Create: `app/v15/runtime.py`
- Create: `scripts/v15_replay.py`
- Create: `scripts/v15_paper.py`
- Create: `scripts/v15_testnet.py`
- Create: `tests/v15/test_runtime.py`

**Interfaces:**
- `AutonomousRuntime.on_event(event: MarketEvent) -> RuntimeState`.
- `AutonomousRuntime.run(events: Iterable[MarketEvent]) -> RuntimeReport`.
- `AutonomousRuntime.shutdown(reason: str) -> None`.

The runtime must execute exactly this sequence:
`event -> integrity/book -> causal features -> frozen model -> economic gate -> risk gate -> execution -> reconciliation -> journal`.

- [ ] **Step 1: Write a deterministic integration fixture with known events and expected NO_TRADE/order/fill transitions.**
- [ ] **Step 2: Add tests proving no order can occur before book readiness, model verification, positive economic gate, and risk approval.**
- [ ] **Step 3: Add tests proving any integrity/model/cost/risk failure forces a safe state.**
- [ ] **Step 4: Run `pytest tests/v15/test_runtime.py -q` and verify failure.**
- [ ] **Step 5: Implement the runtime as dependency-injected components so replay/paper/testnet use identical decision logic.**
- [ ] **Step 6: Implement the replay CLI with deterministic seed/config/model/data hashes and machine-readable output.**
- [ ] **Step 7: Implement the paper CLI using the real feed and simulated execution only.**
- [ ] **Step 8: Implement the testnet CLI requiring explicit user-supplied credentials, while retaining the same risk/economic gates.**
- [ ] **Step 9: Run `pytest tests/v15/test_runtime.py tests/test_core.py tests/test_decision.py tests/test_execution.py -q`.**
- [ ] **Step 10: Commit `feat: add V15 autonomous runtime`.**

---

### Task 7: Evidence chain, validation runner, and production gate

**Files:**
- Create: `app/v15/evidence.py`
- Create: `tests/v15/test_evidence.py`
- Create: `scripts/v15_validate.py`
- Create: `data/evidence/v15/.gitkeep`
- Create: `docs/V15_PRODUCTION_GATE.md`

**Interfaces:**
- `EvidenceWriter.write_run(metadata, metrics, gates) -> str` returning the artifact path.
- `EvidenceWriter.final_status() -> dict`.
- `ValidationRunner.run(calibration_data, forward_data, config) -> dict`.

Evidence must record immutable data/config/model hashes, sample counts, feature schema, gross/net expectancy, execution-cost decomposition, confidence interval/uncertainty, regime results, and every gate decision.

- [ ] **Step 1: Write failing tests for evidence completeness, hash linkage, chronological split enforcement, and failed-gate propagation.**
- [ ] **Step 2: Run `pytest tests/v15/test_evidence.py -q` and verify failure.**
- [ ] **Step 3: Implement JSON evidence records with stable ordering and atomic writes.**
- [ ] **Step 4: Implement validation checks that reject overlapping calibration/forward timestamps and any attempt to use forward data for calibration.**
- [ ] **Step 5: Implement confidence intervals/uncertainty reporting without using the forward set for model selection.**
- [ ] **Step 6: Generate `FINAL_STATUS` and production-gate documents from evidence, not hand-edited conclusions.**
- [ ] **Step 7: Run `pytest tests/v15/test_evidence.py -q`.**
- [ ] **Step 8: Commit `feat: add V15 evidence and validation gate`.**

---

### Task 8: Full regression, replay, paper smoke test, and release decision

**Files:**
- Modify: `README.md` to document V15 commands and the permanent live-trading lock condition.
- Modify: `FINAL_ALGORITHM_STATUS.md` only after machine-readable evidence exists.
- Create: `docs/V15_RUNBOOK.md`
- Test: `tests/` full suite plus `tests/v15/`.

- [ ] **Step 1: Run the complete legacy suite exactly as the repository specifies: `pytest -q`.**
- [ ] **Step 2: Record the baseline failures separately from V15 regressions; do not edit tests to make failures disappear.**
- [ ] **Step 3: Run deterministic V15 replay twice over the same captured dataset and compare output hashes/metrics for exact reproducibility.**
- [ ] **Step 4: Run the paper runtime long enough to verify feed recovery, stale-data halting, order lifecycle simulation, restart/reconciliation, and clean shutdown.**
- [ ] **Step 5: Run the validation runner and verify that production remains locked if forward net expectancy, statistical robustness, execution cost, or regime gates fail.**
- [ ] **Step 6: Run `pytest -q` again and verify no new regressions.**
- [ ] **Step 7: Produce the final V15 evidence chain and update status documents from the generated evidence.**
- [ ] **Step 8: Commit `test: verify V15 end-to-end pipeline`.**

No step in this task may enable real-money order submission merely because the software pipeline is operational. Economic validity and explicit production authorization remain separate gates.

---

## Verification Checklist

After all tasks, the executor must be able to demonstrate:

1. Same captured event stream produces the same feature/model/decision output on repeated replay.
2. A future event cannot alter an earlier feature snapshot.
3. Sequence gaps and stale data force a safe state.
4. Model checksum/schema mismatches prevent trading.
5. Positive AUC/statistical discrimination does not bypass the economic gate.
6. Cost decomposition is visible per decision/run.
7. Risk limits and kill switches are enforced before order submission.
8. Partial fills, rejects, cancellations, timeouts, and restart reconciliation are handled deterministically.
9. Paper mode cannot submit real orders.
10. Testnet mode is isolated from production endpoints.
11. Live mode is hard-locked until explicit authorization and all required gates pass.
12. Evidence is sufficient to reconstruct exactly which data, model, configuration, costs, and gates produced each result.

## Final Acceptance Criterion

The project may be called **technically complete** only when all software gates, tests, replay, paper runtime, evidence generation, and fail-closed controls work end-to-end.

It may be called **economically deployable** only if independent unseen data demonstrates positive net expectancy after realistic execution costs with adequate uncertainty and robustness evidence. A technically complete but economically failed V15 remains locked from live trading.
