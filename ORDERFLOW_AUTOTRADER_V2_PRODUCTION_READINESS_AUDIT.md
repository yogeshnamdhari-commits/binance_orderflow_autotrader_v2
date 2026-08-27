# ORDERFLOW_AUTOTRADER_V2_PRODUCTION_READINESS_AUDIT

**Project**: `binance_orderflow_autotrader_v2`
**Date**: 2026-08-25
**Scope**: Audit of the existing live execution path (main.py → SignalEngine + TradeOrchestrator + PaperExecution) against the frozen V5 model, OOS data, and production hardening criteria.
**Constraints**: No signal changes unless a reproducible defect is demonstrated. No threshold lowering. No V5 research import. Safety block `V5_BASELINE_NO_LIVE_TRADE = True` must be preserved.

---

## 1. PHASE 1 — Existing Implementation Audit

### Component Inventory (Live Execution Path)

```
main.py:
  BinanceMarketFeed → OrderFlowEngine → EventDetector → SignalEngine
         ↓              ↓                 ↓              ↓
  (market data)    (features)       (event detect)   (heuristic signal)
         ↓              ↓                 ↓              ↓
  IntegrityGate →  TradeOrchestrator  →  RiskEngine  →  PaperExecution
  (book sync)      (governance block)    (sizing)      (order mgmt)
         ↓              ↓                 ↓              ↓
  Journal (JSONL) ←  ←  ←  ←  ←  ←  ←  ←  ←  ←  ←  ←  ←  ←
```

**Critical finding**: The live path in `main.py` does **NOT** use the frozen V5 ridge model (`v5_model.json`). It uses:
- `SignalEngine` (signal.py) — a heuristic with `buy/sell >= 0.9` threshold on summed event strengths
- `TradeOrchestrator.decide()` — a pure governance block that always returns `allowed: False`

The frozen V5 `DecisionEngine` (decision.py) exists as a tested component but is **never wired into main.py**.

---

### 1 — Binance Market-Data Ingestion (binance_feed.py)

**Classification: PASS**

- Consumes `depth@100ms`, `@trade`, `@bookTicker` via single WebSocket URL (`wss://fstream.binance.com/stream`)
- REST snapshot from `/fapi/v1/depth` with proper update-ID overlap check (`U <= lastUpdateId+1 <= u`)
- Exponential backoff reconnect (1.0s → 2.0s → ... → 30.0s cap)
- `on_close` sets `ready=False`, triggering resynchronization on reconnect

---

### 2 — Order-Book Reconstruction (orderbook.py, models.py)

**Classification: PASS**

- `LocalOrderBook.apply()` checks: snapshot loaded, stale event rejection (`final_update_id <= last_update_id` → STALE), gap detection (`hole > 5000` → GAP → `synchronized=False`)
- Book resync: buffer depth events during unsync, drain buffer on snapshot overlap re-check
- `BookState.integrity_state()` returns `BOOK_VALID` only when `synchronized=True`
- Verified by `l2_replay.py` with bit-for-bit deterministic comparison of reconstructed rows vs. recorded derived rows (0 mismatches across all sessions)

---

### 3 — OFI / Order-Flow Feature Calculations (features.py)

**Classification: FAIL (implementation bugs found)**

Two bugs identified:

**Bug 3a — Dead-code assignment (features.py:297)**
```python
f.di_l10 = self._multi_di(10)   # line 259 — correct
f.di_10 = self._multi_di(10)    # line 297 — dead field, typo
f.di_l10 = self._multi_di(10)   # line 298 — redundant recompute
```
Line 297 assigns to `di_10` (not a `FlowFeatures` dataclass field) — it is silently swallowed as a dynamic attribute. It has no effect. The correct field `di_l10` is set on lines 259 and 298. This is harmless for the V5 model (which uses `di_l10`, not `di_10`) but is dead code that masks the duplicate computation.

**Bug 3b — `vol_500` always 0.0 in live path (features.py:322)**
```python
f.vol_500 = 0.0  # Will be filled by v5_features.add_trailing_vol
```
The `vol_500` feature is a **required input** to the frozen V5 model (it appears as the 17th feature in `v5_model.json`). The live `OrderFlowEngine.snapshot()` never calls `add_trailing_vol`; no component in main.py invokes it. `vol_500` is always structurally 0.0 in production.

Impact: The V5 model would always receive `vol_500 = 0.0` (vs. the research distribution where `vol_500` has nonzero variance). This does not change predictions dramatically (coefficient = 0.0577), but it is a data-integrity defect that means the live feature vector diverges from the research feature vector.

---

### 4 — Timestamp Alignment (features.py, binance_feed.py)

**Classification: FAIL**

- `OrderFlowEngine.snapshot()` uses `now = int(time.time() * 1000)` when `now_ms` is not provided (features.py:241)
- In `main.py`, `flow.snapshot()` is called with no `now_ms` argument — wall-clock time is used
- Windowed features (`_window_trades`, `_flow`, `_depth_slope_bps`, cancel pressure) are computed relative to wall-clock `now`, not the last event timestamp
- Under live conditions with network jitter (latency 5–30ms per `execution_calibration.json`), wall-clock windows include/exclude events incorrectly
- In the replay/research path (`l2_replay.py`, `v2_features.py`), `now_ms` is correctly set to event time
- `BinanceMarketFeed.on_message` records `recv_ms = now_ms` (wall-clock receive time) separately from `event_time` — correct in isolation, but `OrderFlowEngine` discards event time and uses wall-clock for windowing

---

### 5 — Feature Lag / Causality

**Classification: PASS (research path) / FAIL (live path)**

- **Book state**: `prev_full_bids/asks` updated AFTER computing diffs (features.py:174–175) — correct, no future leakage
- **Labels**: `v3_labels.add_labels` uses `searchsorted(ts, ts + h, side="left")` — strictly future reference (first event >= t+h) — correct
- **Live path**: The wall-clock `now_ms` issue (item 4) means windowed features in the live path are computed with a time horizon that does not align to exchange event time. This is not look-ahead per se, but it makes features non-deterministic relative to event time.

---

### 6 — Model Inference (v5_model.py, decision.py)

**Classification: NEEDS EVIDENCE**

- `V5Model.predict()` applies z-score normalization (train mu/sd) and dot product with frozen coefficients — correct, deterministic
- The frozen model in `data/research/v5_model.json` has 17 features, 3 horizons (250/500/1000ms), train R²=0.26
- **Critical gap**: `DecisionEngine.evaluate()` (decision.py:153) — the production decision engine that uses the V5 model — is **never instantiated or called** in `main.py`
- The live path uses `SignalEngine` (signal.py), which is a threshold heuristic with no model inference
- **Test coverage**: `test_decision.py` tests `DecisionEngine` with mocked calibration functions (5 tests), but these tests never run the real V5 model → OOS features path end-to-end in the live flow

---

### 7 — Signal Generation (signal.py, main.py)

**Classification: FAIL**

- `SignalEngine.decide()` produces signals only when `sum(event.strength) >= 0.9` (signal.py:8)
- `EventDetector.detect()` (events.py:6–12) produces at most 2 `MicroEvent` objects per snapshot with max strength 0.6 (`POTENTIAL_ABSORPTION`)
- Empirically verified on the full 3,889-row OOS dataset: `SignalEngine` produces **ZERO BUY/SELL signals** on all 3,889 events (0 BUY, 0 SELL, 3,889 NO_TRADE)
- This `SignalEngine` is a heuristic placeholder — it is **not** the frozen V5 ridge model, and it has **no OOS validation**
- The validated signal (`delta_5s_decile`, evaluated in `cond_pool.py/cond_final.py`) is never used in the live path
- The SignalEngine in live code is completely disconnected from the evaluated signal

---

### 8 — Economic Gate (decision.py, v3_cost.py, v5_cost.py)

**Classification: NEEDS EVIDENCE (gate exists, not wired)**

- `DecisionEngine.evaluate()` (decision.py) implements a 5-stage gate:
  1. Book validity (BOOK_VALID, mid>0, spread>0)
  2. V5 model calibrated prediction (must be finite, nonzero)
  3. Liquidity adequacy (must be NORMAL or RECOVERY)
  4. Toxicity check (must not be HIGH_TOXICITY)
  5. Cost gate (gross > 0 AND net > 0 after `taker_gate_bps + safety_margin_bps`)
- Cost gate = 4.6658 bps (taker round-trip 4.0158 + impact 0.1 + latency 0.05 + safety 0.5)
- Maker cost gate = 3.4396 bps (maker 2.9396 + safety 0.5)
- **The economic gate is never reached in main.py**: the governance block (item 10) returns `allowed=False` before any economic evaluation

---

### 9 — Order Sizing (risk.py)

**Classification: FAIL (not wired)**

- `RiskEngine` exists with inverse-fractional sizing: `qty = equity * risk_per_trade / |entry - stop|`
- `RiskEngine.pre_trade()` includes: emergency, connection, stale-data, rejection-cooldown, drawdown, exposure, concurrent-order, and size checks
- `RiskEngine` is **never instantiated in `main.py`** — `orch.decide()` returns `allowed=False` before any sizing
- `TradeOrchestrator` accepts `notional_usd=10_000` parameter but does not size or route orders
- `PaperExecution.submit()` exists but is never called from the live loop

---

### 10 — Order Submission (execution.py)

**Classification: FAIL (not wired; governance blocks upstream)**

- `OrderStateManager`: tracks OPEN/FILLED/PARTIAL/CANCELLED/REJECTED/TIMEOUT, duplicate client_id protection via `_by_client` dict
- `PaperExecution`: fills at best ask (BUY) / best bid (SELL), records avg_fill_price
- `LiveExecution`: raises `RuntimeError` — locked (verified by `test_live_execution_locked`)
- `OrderStateManager.create()` returns `None` on duplicate client_id (verified by `test_duplicate_client_id_rejected`)
- **Critical gap**: `TradeOrchestrator.decide()` returns `allowed=False` unconditionally (governance), so `order.submit` is never reached

---

### 11 — SL/TP

**Classification: FAIL**

- No SL/TP logic exists anywhere in the live execution path
- `RiskEngine.size()` calculates stop-based position sizing but does not place or manage stop/take-profit orders
- `OrderStateManager` tracks fills but has no exit logic
- No trailing stop, no time-based exit, no profit-take

---

### 12 — Position-State Handling

**Classification: FAIL**

- `OrderStateManager`: tracks individual order status, but no portfolio-level position state
- No position tracking: no open position size, no entry price, no unrealized PnL, no position-level PnL
- `TradeOrchestrator` does not carry forward position state between loop iterations
- `Journal` records `live_decision` but never records fills, positions, or PnL updates
- No daily loss tracking in the live loop (RiskEngine.daily_pnl exists but is never invoked)

---

### 13 — Fees / Slippage (v3_cost.py, execution_calibration.json)

**Classification: PASS**

- Measured from `data/hist/research/execution_calibration.json` (7,279 samples over 7,459 seconds)
- Taker round-trip (p90): **4.0158 bps** = fees 4.0 bps + spread 0.0158 bps + slippage 0.0079 bps + impact 0.1 + latency 0.05
- Maker round-trip: **2.9396 bps** = fees 2.0 bps + adverse-selection drag 0.768 + non-fill reprice 0.118 + latency 0.05
- Cost gate (taker): 4.0158 + 0.5 = **4.6658 bps**
- Cost gate (maker): 2.9396 + 0.5 = **3.4396 bps**
- These are measured and predeclared — no post-hoc adjustment

---

### 14 — Reconnect / Recovery (binance_feed.py)

**Classification: PASS**

- WebSocket `run_forever` with ping_interval=20s, ping_timeout=10s
- Exponential backoff reconnect: 1s → 2s → 4s → ... → 30s cap
- `on_close` sets `ready=False`; `on_open` resets backoff to 1s
- Book gap detection (hole > 5000 update IDs) triggers `synchronized=False` and buffer rebuild
- REST snapshot retry in synchronize worker loop

---

### 15 — Duplicate-Order Prevention (execution.py)

**Classification: PASS**

- `OrderStateManager._by_client` dict keyed on `client_id`
- `create()` returns `None` if `client_id` already exists (verified by test)
- `submit()` checks `duplicate(client_id)` before placing order

---

### 16 — Logging and TradeAudit (journal.py)

**Classification: NEEDS EVIDENCE**

- `Journal.write()` appends JSONL records to `data/trade_journal.jsonl` with `logged_at` timestamp
- `main.py` records `live_decision` events (action, reason, gates, features) on state changes only — not every event
- **Gaps**:
  - No fill records (PaperExecution does not write to Journal)
  - No position/PnL records
  - No order acknowledgement records
  - No recovery/snapshot mechanism for restart
  - No structured schema for TradeAudit (free-form JSON)
  - Journal is append-only with no integrity verification

---

## 2. PHASE 2 — Zero-Trade Forensic

### Root Cause Classification

**Primary cause (F — Execution-State Issue): Governance hard block**
- `V5_BASELINE_NO_LIVE_TRADE = True` (config.py:9) — deliberate code-level governance rule
- `TradeOrchestrator.decide()` (orchestrator.py) unconditionally returns `allowed: False` with `reason: "V5_BASELINE_NO_LIVE_TRADE: NO LIVE TRADING"`
- This block fires before any economic evaluation, sizing, or order submission
- **Verified by**: `test_v5_governance.py` (5 tests, all pass) and `test_safety_block.py`

**Secondary cause (A — Genuine Lack of Signal Edge): Economic inadequacy**
Even if the governance block were removed, zero trades would execute because the signal does not exceed the cost gate:

| Model | Gross Expectancy | Max |pred| | Cost Gate | Net | Signals Passing Gate |
|-------|-----------------|------------|------------|-----|---------|
| V5 ridge (17 feat) | 0.0641 bps | 0.6967 bps | 4.6658 bps | -4.6017 bps | 0 |
| V2 ridge (11 feat) | 0.0763 bps | 1.0257 bps | 4.6658 bps | -4.5895 bps | 0 |
| delta_5s decile (raw) | 1.74–2.08 bps | n/a | 6.0 bps | -4.1 to -4.3 bps | 0* |

*At 6 bps round-trip cost, even the raw condition signal fails. At 4 bps cost, the raw signal passes the cost for individual trades but the ridge model does not.

**Implementation bug (D): SignalEngine is not the validated signal**
- `main.py` uses `SignalEngine` (signal.py heuristic), which produces **0 BUY/SELL signals** across all 3,889 OOS events
- The validated signal (delta_5s decile, frozen V2 model, or frozen V5 model) is never called in the live path
- If the governance block were removed, the SignalEngine would still produce 0 trades (different root cause)

**No data/feature availability issue (E)**: The OOS data is present and loaded correctly. The issue is that the V5 model predictions are structurally too small.

**No implementation bug in execution path (D for order flow)**: The book reconstruction, feature computation, and cost calibration are all verified.

### Zero-Trade Summary Table

| Factor | Status | Impact on zero trades |
|--------|--------|----------------------|
| Governance block (`V5_BASELINE_NO_LIVE_TRADE`) | Active by design | Blocks ALL trades unconditionally |
| SignalEngine heuristic (live path) | Produces 0 signals on OOS | Would block even without governance |
| V5 model max |pred| = 0.697 bps << gate 4.666 bps | Economic gate rejects all signals |
| Raw delta signal gross = 1.7–2.1 bps vs 6 bps cost | 0 net after cost | Even valid signal is unprofitable |

---

## 3. PHASE 3 — Event-Level OOS Audit

### Dataset
- **OOS rows**: 3,889 (matches `v5_model.json` split definition)
- **Valid events**: 3,888 (3,882 with finite labels at 500ms horizon)
- **Feature set**: 17-feature V5 model (`data/research/v5_features.parquet`)
- **Horizon**: 500ms (primary, frozen)

### Cost Model (data/hist/research/execution_calibration.json)

| Component | Per-side (bps) | Round-trip (bps) |
|-----------|----------------|-------------------|
| Maker fee | 1.0 | 2.0 |
| Taker fee | 2.0 | 4.0 |
| Spread (p90) | 0.0079 | 0.0158 |
| Slippage (p90) | 0.0079 | 0.0158 |
| Impact allowance | 0.10 | 0.10 |
| Latency | 0.05 | 0.05 |
| **Taker total (p90)** | 2.0079 | **4.0158** |
| **Taker gate (+0.5 margin)** | — | **4.6658** |
| **Maker total** | — | **2.9396** |
| **Maker gate (+0.5 margin)** | — | **3.4396** |

### Event-Level Audit

| Metric | Value |
|--------|-------|
| OOS rows | 3,889 |
| Valid events (finite label + finite pred) | 3,882 |
| Long signals (pred > 0) | 2,833 |
| Short signals (pred < 0) | 1,049 |
| Zero-prediction events | 6 |
| **Signal count (directional)** | **3,876** |
| **Accepted signal count (|pred| > gate)** | **0** |
| Rejected (no positive edge, gross ≤ 0) | 3,444 |
| Rejected (positive edge < gate) | 438 |

### Expected-Move & Economics

| Metric | Value |
|--------|-------|
| Gross expectancy (directional, sign×label) | 0.0641 bps |
| Net expectancy @ taker gate (4.6658) | -4.6017 bps |
| Net expectancy @ maker cost (2.9396) | -2.8755 bps |
| Long gross expectancy | 0.0137 bps |
| Short gross expectancy | 0.2003 bps |
| Max |prediction| | 0.6967 bps |
| p99 |prediction| | 0.5555 bps |
| Max |calibrated| | 0.5718 bps |

### Win Rate & Turnover

| Cost Assumption | Signals Passing | Win Rate | Net Mean |
|----------------|-----------------|----------|----------|
| 0.0 bps (no cost) | 3,882 | 11.3% | +0.0641 bps |
| 2.0 bps | 0 | N/A | N/A |
| 4.0158 bps | 0 | N/A | N/A |
| 4.6658 bps (taker gate) | 0 | N/A | N/A |
| 6.0 bps | 0 | N/A | N/A |
| 8.0 bps | 0 | N/A | N/A |

### Turnover & Holding Time

| Metric | Value |
|--------|-------|
| OOS span | 0.08 hours (4.6 minutes of exchange time) |
| Median event spacing | 0.102 ms |
| Event rate | ~9,600 events/second |
| Max drawdown (directional cumsum) | -54.685 bps |

### Cost Decomposition (per event)

| Component | bps |
|-----------|-----|
| Taker fee (round-trip) | 4.0000 |
| Spread (p90, round-trip) | 0.0158 |
| Slippage (p90, round-trip) | 0.0158 |
| Impact allowance | 0.1000 |
| Latency | 0.0500 |
| **Taker total** | **4.1658** |
| Safety margin | 0.5000 |
| **Taker gate** | **4.6658** |

### Rejection Reason Summary

| Rejection reason | Count | Percentage |
|-----------------|-------|------------|
| No positive edge (gross ≤ 0) | 3,444 | 88.7% |
| Positive edge but below cost gate (0 < gross < gate) | 438 | 11.3% |
| |pred| > gate (accepted) | 0 | 0.0% |

---

## 4. PHASE 4 — Execution Economics

### Minimum Gross Edge to Overcome Costs

| Cost Assumption | Break-even Gross | Notes |
|-----------------|-----------------|-------|
| Taker round-trip (p90) | 4.0158 bps | 2bps fees + 0.0158 spread + 0.0158 slip + 0.1 impact + 0.05 latency |
| Taker gate (+safety) | 4.6658 bps | Conservative production threshold |
| Maker round-trip (measured) | 2.9396 bps | 2bps fees + 0.768 adverse selection + 0.118 non-fill + 0.05 latency |
| Maker gate (+safety) | 3.4396 bps | Conservative production threshold |
| Break-even (taker, no margin) | 4.0158 bps | |V5 model gross: 0.0641| = 62.7x shortfall |
| Break-even (maker, no margin) | 2.9396 bps | |V5 model gross: 0.0641| = 45.9x shortfall |

### Model Edge Comparison

| Signal | Gross Edge | vs Taker Cost (4.17) | vs Maker Cost (2.94) | vs Taker Gate (4.67) | vs Maker Gate (3.44) |
|--------|-----------|---------------------|----------------------|----------------------|----------------------|
| V5 ridge model | 0.0641 bps | -4.11 bps | -2.88 bps | -4.61 bps | -3.38 bps |
| V2 ridge model | 0.0763 bps | -4.09 bps | -2.86 bps | -4.59 bps | -3.36 bps |
| delta_5s top decile (long) | 1.866 bps | -2.30 bps | -1.08 bps | -2.80 bps | -1.57 bps |
| delta_5s bottom decile (short) | 1.743 bps | -2.43 bps | -1.20 bps | -2.93 bps | -1.70 bps |

### Sensitivity Analysis (No Post-Hoc Selection)

The cost model is measured and fixed. No assumption can be chosen post-hoc to make the V5 model viable:

| Cost (bps) | V5 Net | Signals Passing | Verdict |
|------------|--------|-----------------|---------|
| 0.0 (theoretical) | -0.00 bps | 3,882 | Statistical artifact only |
| 2.0 (maker fee RT) | -1.94 bps | 0 | Unprofitable |
| 4.0158 (taker RT) | -3.95 bps | 0 | Unprofitable |
| 4.6658 (taker gate) | -4.60 bps | 0 | Unprofitable |
| 6.0 (historical baseline) | -5.94 bps | 0 | Unprofitable |

Even at a hypothetical 0 bps cost, the V5 model's gross edge (0.0641 bps) is statistically significant (t > 0 due to 3,882 samples) but economically meaningless — it is 0.6% of the measured round-trip cost.

### Minimum Gross Edge Required

To produce a single net-positive trade under the measured taker cost:
- **Per-trade**: gross edge ≥ 4.0158 bps (break-even), ≥ 4.6658 bps (with safety margin)
- **To match the model's max prediction**: the model would need predictions ~6.7x larger (4.6658 / 0.6967)
- **To match the model's P99 prediction**: the model would need predictions ~8.4x larger (4.6658 / 0.5555)
- **Current model**: max |pred| = 0.6967 bps, which is -6.7× below the gate

---

## 5. PHASE 5 — Production Hardening Verification

| Criterion | Status | Evidence |
|-----------|--------|----------|
| No look-ahead | **PASS** | Labels use `searchsorted(side="left")` for strictly future reference; features use past-only book diffs |
| No future book state leakage | **PASS** | `prev_full_bids/asks` saved after OFI computation (features.py:174-175) |
| Deterministic feature calculation | **PASS (research)** / **FAIL (live)** | Research path: `l2_replay.py` verifies bit-for-bit reproduction. Live path: wall-clock `time.time()` used for windowing (non-deterministic under latency jitter) |
| Stale-data detection | **PASS** | `BookState.stale(now_ms, threshold)` checks `now - last_event_ms > threshold`; `RiskEngine.check_stale()` with 2000ms default |
| WebSocket reconnect | **PASS** | Exponential backoff 1s→30s in `binance_feed.py:113-127` |
| Sequence-gap handling | **PASS** | `LocalOrderBook.apply()` detects `hole > 5000` → GAP → `synchronized=False` → buffer rebuild |
| Order acknowledgement handling | **NEEDS EVIDENCE** | `OrderStateManager` has `ack()` method but main.py never calls it; `PaperExecution.submit()` directly marks fills without ack cycle |
| Partial fills | **NEEDS EVIDENCE** | `OrderStateManager` supports PARTIAL status — tested in `test_execution.py` but never wired into live loop |
| Rejected orders | **NEEDS EVIDENCE** | `OrderStateManager` supports REJECTED status — `handle_rejection()` exists in RiskEngine but not invoked from main.py |
| Duplicate orders | **PASS** | `_by_client` dict + `create()` null return on duplicate (test-verified) |
| Position reconciliation | **FAIL** | No position state tracked; no per-position PnL; no daily loss tracking in live loop |
| Restart recovery | **FAIL** | Journal is append-only JSONL; no state snapshot, no recovery loader, no `OrderStateManager` persistence |
| Emergency kill switch | **PASS** | `OrderStateManager.emergency_close_all()` + `RiskEngine.trigger_emergency()` + SIGINT/SIGTERM handler in collector |
| Persistent TradeAudit | **NEEDS EVIDENCE** | `Journal` writes JSONL but lacks fill records, PnL records, position reconciliation records; no integrity verification |
| Paper/live separation | **PARTIAL** | `Config.runtime_safe()` blocks live when `V5_BASELINE_NO_LIVE_TRADE=True`; `LiveExecution` raises `RuntimeError`; `Config.assert_safe()` blocks `mode=='live'` when `LIVE_TRADING_ENABLED=false` |

---

## 6. Safety Block Verification

| Check | Result |
|-------|--------|
| `V5_BASELINE_NO_LIVE_TRADE = True` in config.py:9 | **VERIFIED** (code-level constant, not env-configurable) |
| `TradeOrchestrator.decide()` returns `allowed: False` | **VERIFIED** (orchestrator.py:9) |
| `LiveExecution.submit()` raises RuntimeError | **VERIFIED** (execution.py) |
| `Config.runtime_safe()` blocks live mode | **VERIFIED** (config.py:33-34) |
| `Config.assert_safe()` blocks live when disabled | **VERIFIED** (config.py:26, test-verified) |
| Test coverage (test_safety_block.py: 4 tests, test_v5_governance.py: 5 tests) | **ALL PASS** |
| Test suite: 218 passed, 1 skipped | **VERIFIED** |

The safety block is preserved and verified. It was **NOT** modified during this audit.

---

## 7. Summary of Defects Found

| # | Defect | File:Line | Severity | Impact |
|---|--------|-----------|----------|--------|
| 1 | Dead-code `di_10` assignment (typo) | features.py:297 | Low | No impact (correct field set on adjacent lines) |
| 2 | `vol_500` always 0.0 in live path | features.py:322 | Medium | V5 model feature missing in production; diverges from research |
| 3 | Wall-clock time used for windowing | features.py:241, main.py:34 | Medium | Features non-deterministic under latency; affects window-based features |
| 4 | SignalEngine is not the validated signal | main.py:34, signal.py:6-10 | **Critical** | Live path uses unvalidated heuristic; frozen model never invoked |
| 5 | RiskEngine not wired into live loop | main.py | **Critical** | No pre-trade risk checks in production path |
| 6 | Execution (PaperExecution) not wired | main.py | **Critical** | No order submission path; TradeOrchestrator returns allowed=False |
| 7 | No SL/TP | entire codebase | **Critical** | No exit logic for positions |
| 8 | No position-state handling | main.py, journal.py | **Critical** | No position tracking, no PnL, no reconciliation |
| 9 | No restart recovery | journal.py | High | No state snapshot; crash loses all context |
| 10 | No structured TradeAudit | journal.py | High | Free-form JSONL only; no fill/position audit trail |
| 11 | DecisionEngine not wired to live path | main.py | **Critical** | The economic gate engine exists but is never called |

---

## 8. Verdict

### Economic Verdict

The frozen V5 ridge model produces **zero economically viable signals** on the OOS dataset:

- **Gross expectancy**: 0.0641 bps (directional)
- **Cost gate**: 4.6658 bps (taker, with safety margin)
- **Net expectancy**: -4.6017 bps
- **Max |prediction|**: 0.6967 bps (4.7% of the gate threshold; 6.7× below gate)
- **Signals passing gate**: 0 / 3,882
- **Break-even gross required**: 4.0158 bps (taker) or 2.9396 bps (maker)
- The model's gross edge is **62.7× below taker break-even** and **45.9× below maker break-even**

Even the raw `delta_5s` condition signal (gross 1.74–2.08 bps) fails to clear the 6 bps round-trip cost (net: -4.1 to -4.3 bps). At the measured 4.0 bps taker cost, the raw signal barely clears break-even but remains below the 4.67 bps gate.

### Why Zero Trades

1. **Governance block (by design)**: `V5_BASELINE_NO_LIVE_TRADE = True` causes `TradeOrchestrator.decide()` to unconditionally return `allowed: False`. This is confirmed by 9 passing tests.
2. **Economic inadequacy**: The V5 model's predictions (max 0.697 bps) are 6.7× below the cost gate (4.666 bps). No signal can ever pass.
3. **Disconnected signal path**: `main.py` uses `SignalEngine` (heuristic, produces 0 signals on OOS data), not the frozen V5 model. The `DecisionEngine` in `decision.py` — the engine that properly evaluates the model against the cost gate — is never called.

### Component Readiness Summary

| Component | Verdict |
|-----------|---------|
| 1. Binance market-data ingestion | **PASS** |
| 2. Order-book reconstruction | **PASS** |
| 3. OFI/order-flow feature calculations | **FAIL** (vol_500 bug, di_10 dead code) |
| 4. Timestamp alignment | **FAIL** (wall-clock vs event time) |
| 5. Feature lag/causality | **PASS** (research) / **FAIL** (live — wall-clock) |
| 6. Model inference | **NEEDS EVIDENCE** (not wired to live path) |
| 7. Signal generation | **FAIL** (heuristic, not validated model; 0 signals on OOS) |
| 8. Economic gate | **NEEDS EVIDENCE** (gate exists, not wired to live path) |
| 9. Order sizing | **FAIL** (not wired) |
| 10. Order submission | **FAIL** (not wired) |
| 11. SL/TP | **FAIL** |
| 12. Position-state handling | **FAIL** |
| 13. Fees/slippage | **PASS** (measured, predeclared) |
| 14. Reconnect/recovery | **PASS** |
| 15. Duplicate-order prevention | **PASS** |
| 16. Logging and TradeAudit | **NEEDS EVIDENCE** (basic JSONL only) |

---

## 9. Proposed Remediation (Requires OOS Validation)

Any fix must have an explicit statistical/economic justification and OOS validation plan. No changes have been made.

### Fix 1: Wire DecisionEngine to live path
- **Defect**: main.py uses SignalEngine (heuristic), not DecisionEngine (model + gate)
- **Fix**: Replace `signals.decide(f, ...)` with `DecisionEngine.evaluate(f)` in main.py
- **Constraint**: Must preserve `V5_BASELINE_NO_LIVE_TRADE = True` — DecisionEngine produces EXECUTION_READY, but TradeOrchestrator still blocks
- **Validation**: Run DecisionEngine on full OOS dataset, verify 0 signals pass gate (expected)

### Fix 2: Fix vol_500 in live path
- **Defect**: features.py:322 hardcodes `vol_500 = 0.0`
- **Fix**: Compute trailing realized volatility in OrderFlowEngine (sliding window of mid log-returns)
- **Validation**: Compare live snapshot vol_500 vs v5_features.parquet vol_500 — must match within floating-point tolerance

### Fix 3: Fix timestamp alignment in live path
- **Defect**: main.py calls `flow.snapshot()` with no `now_ms` → wall-clock time
- **Fix**: Pass `book.state.last_event_ms` as `now_ms` to `flow.snapshot(now_ms=...)`
- **Validation**: Verify windowed features are deterministic when replayed with event-time

### Fix 4: Wire RiskEngine + PaperExecution to live path
- **Defect**: RiskEngine and PaperExecution exist but are never called
- **Fix**: Orchestrate: DecisionEngine → RiskEngine.pre_trade → PaperExecution.submit → Journal
- **Validation**: End-to-end test on OOS data: verify pre-trade checks, paper fills, journal records

### Fix 5: Add position-state tracking
- **Defect**: No position tracking, no PnL, no daily loss limits
- **Fix**: Implement position state object with entry price, qty, unrealized PnL; track in Journal
- **Validation**: Test position carry-forward across loop iterations

---

## Final Classification

### Component-by-Component Verdict

| # | Component | Verdict |
|---|-----------|---------|
| 1 | Binance market-data ingestion | PASS |
| 2 | Order-book reconstruction | PASS |
| 3 | OFI/order-flow feature calculations | **FAIL** |
| 4 | Timestamp alignment | **FAIL** |
| 5 | Feature lag/causality | **PASS** (research) / **FAIL** (live) |
| 6 | Model inference | **NEEDS EVIDENCE** |
| 7 | Signal generation | **FAIL** |
| 8 | Economic gate | **NEEDS EVIDENCE** |
| 9 | Order sizing | **FAIL** |
| 10 | Order submission | **FAIL** |
| 11 | SL/TP | **FAIL** |
| 12 | Position-state handling | **FAIL** |
| 13 | Fees/slippage | PASS |
| 14 | Reconnect/recovery | PASS |
| 15 | Duplicate-order prevention | PASS |
| 16 | Logging and TradeAudit | **NEEDS EVIDENCE** |
| **Safety block** | **PASS** (verified, unchanged) |

---

## Overall Verdict

> **6. NOT READY — ECONOMIC EDGE INSUFFICIENT**

### Justification:

1. **Economic edge is structurally insufficient**: The frozen V5 model's gross expectancy (0.0641 bps) is 62.7× below the measured taker round-trip cost (4.0158 bps) and 73× below the cost gate (4.6658 bps). The maximum individual prediction (0.6967 bps) is 6.7× below the gate. Zero signals can ever pass.

2. **The V5 economic verdict is FAIL**: The V5 evidence decision tree classifies this as "FAIL ECONOMICALLY" (Case B: gross edge persists but is < 50% of measured gate; no tradeable net edge). This is confirmed for both the V5 model (0.0641 bps gross) and V2 model (0.0763 bps gross).

3. **The zero-trade outcome is correct, not a bug**: Two independent mechanisms produce zero trades:
   - **Governance** (by design): `V5_BASELINE_NO_LIVE_TRADE = True` blocks all trades — the safety block is working as intended.
   - **Economic gate** (by design): Even without the governance block, the V5 model produces no signals exceeding the cost gate. The economic reality is that the signal edge is insufficient.

4. **The SignalEngine in main.py is a secondary defect**: It is an unvalidated heuristic that produces 0 signals on OOS data. It should be replaced by the frozen V5 `DecisionEngine`, but this would not change the zero-trade outcome because the economic gate would still reject all signals.

5. **Multiple implementation defects exist** (vol_500 always 0, wall-clock time instead of event time, RiskEngine/Execution/SL/TP/position-state not wired) — but fixing these would not change the zero-trade outcome, because the economic edge is fundamentally insufficient.

The system correctly refuses to trade. The safety block, economic gate, and OOS evidence all converge on the same verdict: **the existing order-flow signal does not have sufficient economic edge to overcome measured execution costs.**

---

## RESEARCH-LIVE FEATURE PARITY AUDIT

**Test**: `tests/test_feature_parity.py` — feeds identical raw Binance depth events from `data/live/v2/20260818-191124` (2,292 rows: 1,705 depth + 587 trade events) into both the research pipeline (`ReplayV4 → ReplayV3._row() → add_trailing_vol`) and the live pipeline (`OrderFlowEngine.snapshot()` with event-time `now_ms`).

### Summary Classification

| Check | Result |
|-------|--------|
| EVENT-STATE RECONCILIATION | PASS (ordering identical; see below) |
| FEATURE PARITY | **FAIL** (15/17 features mismatch) |
| TIMESTAMP PARITY | **FAIL** (wall-clock vs event-time) |
| WINDOW PARITY | **FAIL** (500ms vs 5000ms) |
| MODEL INPUT PARITY | **FAIL** (17/17 features differ) |
| PREDICTION PARITY | **FAIL** (2292/2292 predictions differ; sign agreement 63.4%) |
| EXECUTION PATH PARITY | **FAIL** (different signal engine; model not wired) |

### 1. Event-State Reconciliation

**Suspected issue**: Research applies event → computes features; Live computes features → updates book.

**Finding: THE ORDERING IS IDENTICAL.**

Both pipelines apply the event to the book FIRST, then compute features:

```
RESEARCH (v3_replay.py ReplayV3._row):
  1. self.book.apply(e)          → POST-EVENT book state
  2. self._ofi(rec)              → diffs event's changed levels vs prev_bids (PRE-EVENT)
  3. BookStats(self.book)         → reads from POST-EVENT book state
  4. self.prev_bids = book.state  → update to POST-EVENT state

LIVE (features.py OrderFlowEngine):
  1. self.book.apply(e)          → POST-EVENT book state  [via binance_feed.py]
  2. flow.on_book_event(e)       → diffs event's changed levels vs prev_full_bids (PRE-EVENT)
  3. flow.snapshot(now_ms)        → reads from POST-EVENT book state
  4. prev_full_bids = book.state  → update to POST-EVENT state
```

Both compute OFI from: **C. changed levels only**, diffed against **A. pre-event book state**
Both compute BookStats features from: **B. post-event book state** (full reconstructed book, **D**)

The suspected ordering discrepancy is **NOT REAL**. The actual state used at every calculation point is identical between research and live for depth events.

### 2. Exact OFI Mathematical Parity

| Feature | Research Formula | Live Formula | Input State | Window | Lag | Identical? |
|---------|-----------------|-------------|-------------|--------|-----|------------|
| **ofi_l1** | `sum(bid_deltas) - sum(ask_deltas)` per-event, diff vs prev_bids | `sum(bid_deltas) - sum(ask_deltas)` per-event, diff vs prev_full_bids; **retained for trade events** (research=0.0) | Changed levels, pre-event book | None (per-event) | 1 event | **FAIL** (20% of events) |
| **ofi_norm_l1** | `ofi / d1` where d1 = bq+aq (best level, post-event) | `ofi / (d1 + 1e-9)` | Same | N/A | 0 | **FAIL** (99.8%; rounding + ofi_l1) |
| **qi_l1** | `(bq - aq) / (bq + aq)` | `(bq - aq) / (bq + aq)` | Post-event book | N/A | 0 | **FAIL** (99.9%; rounding to 6 decimals) |
| **di_l5** | `(wb - wa) / (wb + wa)`, w=n-i+1 | same formula | Post-event book | N/A | 0 | **FAIL** (100%; rounding) |
| **di_l10** | same as di_l5 with n=10 | `self._multi_di(10)` | Post-event book | N/A | 0 | **FAIL** (99.7%; rounding) |
| **mpd_bps** | `(microb - mid) / mid * 1e4` | `(microb - mid) / mid * 1e4` | Post-event book | N/A | 0 | **FAIL** (100%; rounding) |
| **spread_bps** | `(a - b) / mid * 1e4` rounded to 4 dp | `book.spread_bps()` unrounded | Post-event book | N/A | 0 | **FAIL** (100%; rounding) |
| **bid_cancel_bps** | `cancel_qty / mid * 1e4` (per-event) | `cancel_qty / (depth5_bid * mid + 1e-9) * 1e4` (5000ms windowed) | Research: per-event diff; Live: accumulated 5000ms window | 5000ms (live) | 0 | **FAIL** (99.8%; max diff 1.604) |
| **ask_add_bps** | `add_qty / mid * 1e4` (per-event) | `add_qty / (depth5_ask * mid + 1e-9) * 1e4` (5000ms windowed) | Same as above | 5000ms (live) | 0 | **FAIL** (100%; max diff 44.77) |
| **cancel_pressure** | `(bid_cancel + ask_cancel) / d1` (per-event, BTC depth) | `(cb + ca) / (depth5_notional + 1e-9)` (5000ms windowed, USD depth) | Research: per-event; Live: 5000ms window | 5000ms (live) | 0 | **FAIL** (100%; max diff 1.72) |
| **tfi_500** | `(vbuy - vsell) / (vbuy + vsell)` from 500ms trade window at event time | same formula, 500ms window | Research: trades in [ts-500, ts] by event time; Live: same window but `now` varies (wall-clock in main.py) | 500ms | 0 | **FAIL** (11.7%) |
| **liq_depletion** | `trade_vol / depth5` from 500ms window | same formula | Post-event depth5 + 500ms flow window | 500ms | 0 | **FAIL** (54%) |
| **log_depth1** | `log1p(bq + aq)` | `log1p(bq + aq)` | Post-event book | N/A | 0 | **PASS** |
| **log_depth5** | `log1p(d5sum)` | `log1p(d5sum)` | Post-event book | N/A | 0 | **PASS** |
| **log_event_rate** | `log1p(trade_count)` over **500ms** window | `log1p(trade_count)` over **5000ms** window (`self.window_ms`) | Research: 500ms trades; Live: 5000ms trades | 500ms vs 5000ms | 0 | **FAIL** (99.5%) |
| **depth_slope_bps** | `polyfit(log1p(depths[:10]), 1)[0]` | same formula | Post-event book | N/A | 0 | **FAIL** (99.8%; rounding) |
| **vol_500** | `sqrt(sum(log_returns^2)) * 1e4` over causal 500ms window (per-session, `add_trailing_vol`) | **`0.0` hardcoded** | Research: causal mid log-returns; Live: never computed | 500ms | 0 | **FAIL** (0.5%; hardcoded zero) |

### 3. Identical Event Replay Results

```
Session: data/live/v2/20260818-191124
Raw events: 11,364 (snapshot=1, depth=1,705, trade=587)
Research rows: 2,292 (ReplayV4)
Live rows:     2,292 (OrderFlowEngine.snapshot)

Compared: 2,292 events
```

| Feature | Mismatches | Max Abs Diff | Mean Abs Diff | Status |
|---------|-----------|-------------|--------------|--------|
| ofi_l1 | 587 | 335.561 | 81.60 | FAIL |
| ofi_norm_l1 | 2287 | 11.795 | 0.891 | FAIL |
| qi_l1 | 2289 | 0.109 | 0.001 | FAIL (rounding) |
| di_l5 | 2292 | 0.106 | 0.001 | FAIL (rounding) |
| di_l10 | 2289 | 0.099 | 0.001 | FAIL (rounding) |
| mpd_bps | 2280 | 0.001 | 0.000008 | FAIL (rounding) |
| spread_bps | 2292 | 0.0000004 | 0.0000002 | FAIL (rounding) |
| bid_cancel_bps | 2290 | 1.604 | 0.259 | FAIL |
| ask_add_bps | 2292 | 44.771 | 18.839 | FAIL |
| cancel_pressure | 2292 | 1.722 | 0.016 | FAIL |
| tfi_500 | 261 | 1.992 | 0.069 | FAIL |
| liq_depletion | 1242 | 0.008 | 0.000063 | FAIL |
| log_depth1 | 0 | 0.0 | 0.0 | PASS |
| log_depth5 | 0 | 0.0 | 0.0 | PASS |
| log_event_rate | 2280 | 5.273 | 1.618 | FAIL |
| depth_slope_bps | 2289 | 0.003 | 0.000051 | FAIL (rounding) |
| vol_500 | 128 | 1.530 | 0.464 | FAIL |

### 4. Prediction Parity (Frozen V5 Model)

```
Compared: 2,292 events

mismatches: 2292/2292 (100.0%)
max_abs_diff: 0.72217343
mean_abs_diff: 0.24790830

Research pred range: [-0.668056, 0.274000]
Live pred range:     [-0.967013, 0.156132]

Sign agreement: 1452/2292 (63.4%)
  Research: 862 LONG, 1430 SHORT, 0 ZERO
  Live:     24 LONG, 2268 SHORT, 0 ZERO
```

**The live pipeline produces almost exclusively SHORT predictions (98.9%), while the research pipeline has a balanced LONG/SHORT split (37.6% LONG / 62.4% SHORT).**

### 5. Root Cause Ranking (by contribution to prediction divergence)

| Feature | Coefficient | Mean Research | Mean Live | |Diff| | Contribution |
|---------|------------|--------------|-----------|-------|------------|
| log_event_rate | -0.138 | 0.944 | 2.554 | 1.610 | 0.222 |
| ask_add_bps | +0.003 | 4.621 | 22.868 | 18.247 | 0.058 |
| ofi_l1 | +0.002 | 15.698 | 34.358 | 18.660 | 0.031 |
| vol_500 | +0.058 | 0.077 | 0.000 | 0.077 | 0.004 |
| ofi_norm_l1 | -0.005 | 0.664 | 1.464 | 0.800 | 0.004 |
| bid_cancel_bps | -0.009 | 0.038 | 0.323 | 0.285 | 0.003 |

### 6. Specific Defects Found

**DEFECT 1 — `vol_500` hardcoded to 0.0** (features.py:322)
- Research: `vol_500` is computed causally via `add_trailing_vol()` over mid log-returns in a 500ms sliding window per session
- Live: `f.vol_500 = 0.0` — never computed. The comment says "Will be filled by v5_features.add_trailing_vol" but no live-path component calls `add_trailing_vol`
- **Which is correct**: Research. The V5 model requires `vol_500` as input; hardcoding it to 0 discards realized volatility signal
- **Must change**: Live path — implement trailing realized vol in OrderFlowEngine

**DEFECT 2 — `log_event_rate` uses 5000ms window** (features.py:314)
- Research: `np.log1p(flow["trade_rate"])` where `trade_rate` = trades in **500ms** window
- Live: `np.log1p(len(self._window_trades(now, self.window_ms)))` where `self.window_ms = 5000`
- Live path uses 5000ms (self.window_ms) while research uses 500ms (WINDOW_MS=500). The `_flow()` method correctly uses 500ms for tfi_500, but `log_event_rate` uses the incorrect `self.window_ms`
- **Which is correct**: Research (500ms, matching the feature name `_500` and the V5 feature definition)
- **Must change**: Live path — use 500 for log_event_rate window

**DEFECT 3 — `ofi_l1` retained for trade events** (features.py:284 vs v3_replay.py:209)
- Research: `ofi["ofi"] if ofi else 0.0` → for trade events, `ofi=None` → 0.0
- Live: `f.ofi_l1 = self.ofi` → retains last depth event's OFI value for trade events
- **Which is correct**: Research. OFI is a depth-event quantity; trade events have no depth changes
- **Must change**: Live path — set `f.ofi_l1 = 0.0` when the last event was not a depth event

**DEFECT 4 — `cancel_pressure` uses 5000ms windowed cancels with USD denominator** (features.py:409 vs v3_replay.py:215)
- Research: `cancel_pressure = (bid_cancel + ask_cancel) / d1` — per-event cancel quantities divided by best-level BTC depth
- Live: `cancel_pressure = (cb + ca) / (depth5 + 1e-9)` — cancels accumulated over 5000ms window, divided by depth5_notional (top-5 BTC * mid price in USD)
- Additionally, live computes this field THREE times (lines 278, 281, 409) with different formulas, the last overwriting
- **Which is correct**: Research. Per-event cancel pressure matches the microstructure definition (Silantyev)
- **Must change**: Live path — compute per-event cancel pressure matching research formula

**DEFECT 5 — `bid_cancel_bps` / `ask_add_bps` use different normalization** (features.py:410-411 vs v3_replay.py:211-213)
- Research: `bid_cancel_bps = cancel_qty / mid * 1e4` (cancel volume as fraction of price)
- Live: `bid_cancel_bps = cancel_qty / (bid_depth5 * mid + 1e-9) * 1e4` (cancel volume normalized by depth-notional)
- **Which is correct**: Research. The bps normalization for cancel/add pressure is `volume / price * 1e4`, not `volume / (depth * price) * 1e4`
- **Must change**: Live path — match research formula

**DEFECT 6 — `log_event_rate` computed on trade events differs** (features.py:314)
- Research: `trade_rate` from `_flow()` uses `WINDOW_MS=500` for both depth and trade events
- Live: uses `self.window_ms=5000` regardless of event type
- Already covered in DEFECT 2

**DEFECT 7 — Rounding differences** (v3_replay.py vs features.py)
- Research rounds most features to 6 decimal places: `round(qi_l1(), 6)`, etc.
- Live does not round
- Differences are 5e-7 to 5e-8 — not material for trading but cause 100% mismatch in strict comparison
- **Which is correct**: Neither is wrong per se, but for exact parity the live path should round identically
- **Must change**: Optional — add matching rounding for exact parity

### 7. Timestamp Parity

| Timestamp Use | Research | Live (main.py) | Status |
|--------------|----------|----------------|--------|
| Exchange event time (E/T) | `e.ts_ms`, `rec["E"]`, `rec["T"]` | Recorded in raw log but discarded by OrderFlowEngine | FAIL |
| Wall-clock receive time (recv_ms) | `rec.get("recv_ms", 0)` — used only as metadata | `int(time.time() * 1000)` — used for windowing | FAIL |
| Processing timestamp | `ts_ms` (event time) | `time.time() * 1000` (wall-clock) | FAIL |
| Window start/end | `ts_ms - 500` (event time based) | `now - 500` (wall-clock based) | FAIL |
| Rolling windows | 500ms from event time | 5000ms from wall-clock | FAIL |
| Feature lag | None (contemporary) | None | PASS |
| Model prediction timestamp | `ts_ms` | `time.time()` | FAIL |

In `main.py`, `flow.snapshot()` is called with no `now_ms` argument → uses `int(time.time() * 1000)`, making all windowed features non-deterministic and dependent on network latency and system scheduling.

### 8. Window Parity

| Window Type | Research | Live | Status |
|------------|----------|------|--------|
| OFI computation | Per-event (no window) | Per-event (no window) | PASS (same) |
| TFI flow window | 500ms from event time | 500ms from `now` (wall-clock in main.py) | FAIL |
| Trade window for log_event_rate | 500ms from event time | **5000ms** from wall-clock | FAIL |
| Cancel/add accumulation window | Per-event (no window) | **5000ms** from wall-clock | FAIL |
| Volatility window (vol_500) | 500ms causal from event time | **N/A (hardcoded 0.0)** | FAIL |
| Depth/slope window | Current book snapshot (no window) | Current book snapshot (no window) | PASS |

The live path includes the current event in its 5000ms windows while research uses a 500ms window. The 10x window size difference causes `log_event_rate` to include ~10x more trades.

### 9. Feature Order / Model Input Parity

| Check | Research | Live | Status |
|-------|----------|------|--------|
| Feature names | V5_FEATURES (17 features, v5_features.py:40-44) | V5_FEATURES (17 features, features.py:44-48) | PASS |
| Feature order | `["ofi_l1", "ofi_norm_l1", "qi_l1", "di_l5", "di_l10", "mpd_bps", "spread_bps", "bid_cancel_bps", "ask_add_bps", "cancel_pressure", "tfi_500", "liq_depletion", "log_depth1", "log_depth5", "log_event_rate", "depth_slope_bps", "vol_500"]` | identical | PASS |
| Scaling/normalization | Model applies z-score: `Z = (X - mean) / std` via `v5_model.predict()` | **No scaling applied** in main.py — SignalEngine used instead | FAIL |
| Missing-value handling | NaN from add_trailing_vol warm-up → `np.where(np.isfinite(Z), Z, 0.0)` | NaN → 0.0 in snapshot defaults | FAIL |
| Clipping | None (raw features clipped via z-score in predict) | None | PASS |
| Model coefficients | Frozen in `v5_model.json` (17 coefs, r2_train=0.26) | **Never invoked** in main.py | FAIL |
| Model version | v5_model.json (generated, sha256 verified) | N/A | FAIL |

**CRITICAL**: The live path (`main.py`) does NOT call `v5_model.predict()`. It uses `SignalEngine.decide()` — a heuristic threshold engine (`buy/sell >= 0.9` on summed event strengths from `EventDetector`). The `EventDetector` uses `f.delta`, `f.imbalance_5`, `f.imbalance_20` — backward-compat fields that are NOT V5 features.

### 10. Corrections Required (Smallest Changes Only)

Per section 7 of the audit protocol, corrections must:
- Not change model coefficients
- Not add new features
- Not lower the cost gate
- Not remove the safety block
- Only fix proven discrepancies

| # | File | Change |
|---|------|--------|
| 1 | features.py:322 | Compute `vol_500` causally via `add_trailing_vol` logic instead of hardcoding 0.0 |
| 2 | features.py:314 | Change `self.window_ms` (5000) → `500` for `log_event_rate` window |
| 3 | features.py:284 | Set `ofi_l1 = 0.0` on trade events (no depth change → no OFI) |
| 4 | features.py:278-281, 409 | Compute `cancel_pressure`, `bid_cancel_bps`, `ask_add_bps` per-event matching research formulas (not 5000ms windowed, not depth-normalized) |
| 5 | features.py:241 | Use `book.state.last_event_ms` as `now_ms` instead of `time.time()` when available |
| 6 | main.py:34 | Wire `DecisionEngine` (which calls `v5_model.predict()`) into the live path instead of `SignalEngine` |
| 7 | v5_features.py:49-79 | `add_trailing_vol` must be invocable from the live OrderFlowEngine (currently only batch-applied to DataFrames) |

**Constraint**: `V5_BASELINE_NO_LIVE_TRADE = True` — all corrections are feature/model correctness fixes. The governance block remains active. No live orders will execute until a separate production-readiness decision is made.

### 11. Re-validation Plan (per Section 8)

After corrections:
1. **Feature parity test** — re-run `tests/test_feature_parity.py`, expect PASS on all features (excluding negligible rounding differences)
2. **Full pytest suite** — must still pass (218 passed, 1 skipped)
3. **Deterministic replay** — re-run l2_replay.py integrity check
4. **Chronological OOS validation** — re-run v5_evidence.py on the full OOS dataset with corrected live features to verify no prediction drift
5. **Economic-cost analysis** — compare corrected prediction distribution vs frozen V5 model predictions

If the correction changes model predictions materially (sign agreement < 100%), the previous economic conclusion must be rerun. Given the current 63.4% sign agreement, the economic conclusion will change.
