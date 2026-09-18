# V20 Production Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move V20 from historical replay to a production-capable execution boundary without changing the trading strategy, while keeping real-money submission fail-closed and disabled until execution/reconciliation gates pass.

**Architecture:** Preserve the frozen V20 quote/config path. Add a live market-data adapter, explicit order lifecycle manager, private user-data reconciliation, unified risk/kill controls, and reconciled P&L. Paper/testnet uses the same state/risk interfaces as production; live submission remains gated.

**Tech Stack:** Python 3, existing V20 modules, Binance USDⓈ-M WebSocket/HTTP interfaces, pytest, JSON provenance/state journals.

**Spec:** `docs/superpowers/specs/2026-09-16-v20-production-execution-design.md`

## Global Constraints

- Do not optimize strategy parameters in this implementation.
- Keep `app/mm/config.json` as the authoritative V20 experiment configuration.
- `live_order_submission` remains `false` by default.
- No API secrets may be committed.
- Raw high-volume event files remain local/ignored; manifests, provenance and evidence remain tracked.
- All safety failures resolve to `NO_TRADE`.
- Exchange-confirmed order/position state is authoritative for reconciliation.

---

### Task 1: Harden order lifecycle state machine

**Files:**
- Modify: `app/execution.py`
- Test: `tests/test_execution.py` or the existing execution test module

**Deliverable:** Deterministic order lifecycle with idempotency, acknowledgement timeout, partial-fill accumulation, cancel/replace semantics, and safe restart handling.

- [ ] Add failing tests for OPEN→PARTIAL→FILLED, OPEN→CANCELLED, OPEN→REJECTED, OPEN→TIMEOUT, duplicate client IDs, and restart restoration.
- [ ] Make illegal terminal-state transitions return explicit failures rather than silently mutating state.
- [ ] Add deterministic client-order ID generation using symbol/side/timestamp/sequence inputs without relying on random UUIDs for idempotency.
- [ ] Preserve state journaling and persistence.
- [ ] Run the targeted execution tests and full test suite.

### Task 2: Add live market-data safety boundary

**Files:**
- Create: `app/mm/live_market_data.py`
- Test: `tests/test_mm_live_market_data.py`

**Deliverable:** Normalized live order-book/trade feed with stale-data, sequence-gap, malformed-message and reconnect detection.

- [ ] Define a normalized event interface compatible with the existing V20 book/order-flow inputs.
- [ ] Add sequence continuity checks and monotonic timestamp checks.
- [ ] Add configurable maximum market-data age; stale state must return `NO_TRADE`.
- [ ] Add reconnect state that requires a clean snapshot/resubscription before quoting resumes.
- [ ] Test valid events, gaps, malformed events, stale data and reconnect recovery deterministically.

### Task 3: Add authenticated private user-data state

**Files:**
- Create: `app/mm/user_stream.py`
- Test: `tests/test_mm_user_stream.py`

**Deliverable:** Normalized exchange order/execution/position/account events with heartbeat/keepalive and reconnect state.

- [ ] Define normalized order-update and position-update dataclasses.
- [ ] Track stream health and invalidate execution permission on disconnect/stale heartbeat.
- [ ] Ensure unknown execution/order responses are treated as reconciliation failures.
- [ ] Test fills, partial fills, cancellations, rejections, disconnects and recovery.

### Task 4: Add exchange/local reconciliation

**Files:**
- Create: `app/mm/reconciliation.py`
- Test: `tests/test_mm_reconciliation.py`

**Deliverable:** Continuous comparison of local and exchange order/position state.

- [ ] Compare open orders by client ID/order ID, status, side, quantity and filled quantity.
- [ ] Compare net position and symbol exposure within explicit tolerances.
- [ ] Return a fail-closed reconciliation state on mismatch.
- [ ] Require a fresh exchange snapshot after recovery before quoting resumes.
- [ ] Test matching state, missing order, unexpected order, quantity mismatch, position mismatch and successful recovery.

### Task 5: Unify production risk/kill-switch governance

**Files:**
- Modify: `app/mm/config.py`
- Create: `app/mm/live_risk.py`
- Test: `tests/test_mm_live_risk.py`

**Deliverable:** Hard fail-closed risk gate covering max position, max notional, max order size, max open orders, stale quote, max data latency, daily loss, API error rate, stream health and reconciliation state.

- [ ] Add explicit production risk limits to the authoritative config schema.
- [ ] Implement `can_quote()` and `can_submit()` with deterministic reasons.
- [ ] Make any missing/invalid state fail closed.
- [ ] Add daily-loss and repeated-API-error latches that require explicit reset/reconciliation.
- [ ] Test every kill condition and normal healthy operation.

### Task 6: Reconcile realized + MTM P&L for live accounting

**Files:**
- Create: `app/mm/live_pnl.py`
- Modify: `app/mm/backtest.py` only where shared accounting contracts are required
- Test: `tests/test_mm_live_pnl.py`

**Deliverable:** Live account P&L that separately tracks realized P&L, inventory MTM, fees and execution costs, then produces a single reconciled net value.

- [ ] Define position/average-entry accounting for long and short inventory.
- [ ] Apply exchange-reported fills and fees exactly once.
- [ ] Mark residual inventory to current reconciled mid/mark price.
- [ ] Test flat, long, short, partial-fill and fee cases.
- [ ] Ensure backtest metrics and live account P&L are not conflated.

### Task 7: Wire paper/testnet execution through the same control boundary

**Files:**
- Modify: `app/execution.py`
- Create: `app/mm/execution_gateway.py`
- Test: `tests/test_mm_execution_gateway.py`

**Deliverable:** One execution interface usable by paper/testnet/live implementations, with identical order-state/risk/reconciliation contracts.

- [ ] Define `ExecutionGateway.submit/cancel/replace/reconcile` interfaces.
- [ ] Route `PaperExecution` and `SimulatedExchange` through the gateway.
- [ ] Add a Binance testnet adapter behind a feature flag without enabling mainnet orders.
- [ ] Make submission impossible when risk/reconciliation/stream gates are not green.
- [ ] Test successful order lifecycle plus all rejection/timeout/kill paths.

### Task 8: Add production launch/readiness gate

**Files:**
- Create: `app/mm/production_gate.py`
- Modify: `app/mm/run.py`
- Test: `tests/test_mm_production_gate.py`

**Deliverable:** Explicit preflight that validates code/config provenance, connectivity, stream health, reconciliation, risk state, and live-order flag.

- [ ] Validate current Git commit is available and authoritative config SHA matches the run envelope.
- [ ] Require market-data and private-stream health.
- [ ] Require zero reconciliation mismatches.
- [ ] Require all risk checks green.
- [ ] Require `live_order_submission == false` for paper/testnet mode.
- [ ] Produce a machine-readable readiness report with blocking reasons.

### Task 9: End-to-end deterministic integration validation

**Files:**
- Create: `tests/integration/test_v20_execution_path.py`
- Modify: `README.md` or V20 run documentation

**Deliverable:** One end-to-end test path covering market data → quotes → order lifecycle → fills → reconciliation → P&L → kill switch.

- [ ] Build a deterministic simulated exchange/event stream.
- [ ] Exercise normal quote/fill flow.
- [ ] Inject partial fill, cancel, rejection, timeout, stale feed, disconnect, position mismatch and API-error scenarios.
- [ ] Verify every unsafe state prevents new orders.
- [ ] Run the full Python test suite and compile/import checks.

### Task 10: Controlled testnet readiness package

**Files:**
- Create: `docs/V20_TESTNET_RUNBOOK.md`
- Create: `data/v20_readiness/latest_readiness.json` after the verified run

**Deliverable:** Exact runbook and evidence package for Binance Futures Testnet, with the strategy/config frozen and no optimization loop.

- [ ] Document environment variables without storing secrets.
- [ ] Record Git commit, config SHA-256, code version, test results and readiness checks.
- [ ] Specify one-symbol BTCUSDT controlled test sequence.
- [ ] Define stop conditions and reconciliation procedure.
- [ ] Keep mainnet/live submission disabled until an explicit later deployment decision.

---

## Final Verification

- [ ] `python3 -m pytest` passes.
- [ ] `python3 -m compileall app tests` passes.
- [ ] `python3 -c 'import app.mm'` passes.
- [ ] Deterministic integration test passes.
- [ ] Readiness gate fails closed on every injected unsafe condition.
- [ ] Authoritative config SHA is recorded.
- [ ] Current Git commit is recorded.
- [ ] No secrets or raw large captures are committed.
- [ ] `live_order_submission` remains `false`.
