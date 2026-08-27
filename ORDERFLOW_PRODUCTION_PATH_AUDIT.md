# ORDERFLOW PRODUCTION PATH AUDIT

**Date:** 2026-08-25
**Project:** `binance_orderflow_autotrader_v2`
**Auditor:** Kilo forensic pipeline
**Freeze ID:** `ORDERFLOW_BASELINE_V5` — `V5_BASELINE_NO_LIVE_TRADE = TRUE` throughout

---

## 1. Exact Production Call Graph

### Application Entry Point (`app/main.py`)

```
main.py:9 def main()
  ├─ main.py:11 cfg=Config(); cfg.assert_safe()
  ├─ main.py:12-18  if V5_BASELINE_NO_LIVE_TRADE: print(...)  [governance banner, no exit]
  ├─ main.py:19  book=LocalOrderBook(cfg.levels)
                flow=OrderFlowEngine(book)            ← live feature engine
                detector=EventDetector()              ← simple threshold events
                signals=SignalEngine()                ← simple signal generator
  │   NOTE: DecisionEngine is NOT imported, NOT instantiated, NOT used
  ├─ main.py:20  orch=TradeOrchestrator()            ← governance hard-block
  ├─ main.py:23  gate=IntegrityGate()                 ← book_sync → features → cost → signal_allowed
  ├─ main.py:24  feed=BinanceMarketFeed(cfg, symbol, book, flow)
  ├─ main.py:25  threading.Thread(feed.run)

  Main loop (main.py:28-44):
    ├─ main.py:30  gate.on_book_sync(feed.ready, 'depth@100ms')
    ├─ main.py:31  gate.on_features(feed.ready & book.synchronized, 'book+features')
    ├─ main.py:32  gate.on_cost(True, 'fill calibration loaded')
    ├─ main.py:33  snap=gate.evaluate()               → {BOOK_SYNCED, FEATURES_VALID, COST_VALID, SIGNAL_ALLOWED}
    ├─ main.py:34  f=flow.snapshot()                  → FlowFeatures
                        signals.decide(f, detector.detect(f))  → Signal(BUY/SELL/NO_TRADE)
    ├─ main.py:35-36  if snap['SIGNAL_ALLOWED'] and s.action in ('BUY','SELL'):
    │   cond='delta_5s_top_decile' if BUY else 'delta_5s_bottom_decile'
    │   main.py:38  r=orch.decide(cond, notional_usd=10_000, book, equity, daily_pnl_pct, spread_bps)
    │   main.py:40  decision={'action':('BUY' if r['allowed'] else 'NO_TRADE'), ...}
    │   └─ main.py:48-57  V5_BASELINE_NO_LIVE_TRADE=TRUE → always returns {allowed: False}
    └─ main.py:42-43  journal.write(...)
```

### Market Data Feed (`app/binance_feed.py`)

```
BinanceMarketFeed.__init__(cfg, symbol, book, flow)   [line 19]
  ├─ on_open(ws) → spawn synchronization worker thread
  │   ├─ synchronize() → REST snapshot → buffer depth events → apply to LocalOrderBook
  │   └─ EventReader.load_snapshot(bids, asks) stored in book.state
  ├─ on_message(ws, raw):                    [line 75]
  │   ├─ 'depthUpdate' → DepthEvent(E, U, u, bids, asks)
  │   │   → book.apply(e)  [line 87]
  │   │   → flow.on_book_event(e)  [line 91]
  │   └─ 'aggTrade'/'trade' → TradeEvent(T, a, p, q, m)
  │       → flow.on_trade(e)  [line 93]
  └─ run() → WebSocketApp loop  [line 110]
```

### Feature Engine (`app/features.py`)

```
OrderFlowEngine.__init__(book, window_ms=5000)     [line 116]
  ├─ __init__:   prev_full_bids/asks from book.state; trades=[]; ofi=0; cvd=0; mlofi=[]
  ├─ on_trade(t)    [line 142]  → append to self.trades; update CVD
  ├─ on_book_event(e) [line 152] → compute OFI, cancel_pressure, add/cancel bps
  ├─ snapshot()       [line 251] → FlowFeatures:
  │   ├─ qi_l1 = (bq-aq)/(bq+aq)       [line 269]
  │   ├─ di_l5, di_l10 = _multi_di(5/10) [line 270-271]
  │   ├─ mpd_bps = microprice deviation [line 274]
  │   ├─ ofi_l1, ofi_norm_l1           [line 279-280]
  │   ├─ tfi_500, liq_depletion        [line 297-299]
  │   ├─ delta = _compute_delta()       [line 306] = Σ(buy_qty) - Σ(sell_qty) over 5000ms window
  │   ├─ imbalance_5 = book.imbalance(5) [line 314] = (depth_bid5 - depth_ask5)/(depth_bid5 + depth_ask5)
  │   └─ imbalance_20 = book.imbalance(20) [line 315]
  └─ _window_trades(now, window_ms) [line 193] → non-destructive filtering
```

### Event Detection (`app/events.py`)

```
EventDetector.detect(f)  [line 5]
  ├─ BUY_FLOW:     f.delta > 0 AND f.imbalance_5 > 0.20  → strength = min(1, 0.5 + imbalance_5)
  ├─ SELL_FLOW:    f.delta < 0 AND f.imbalance_5 < -0.20 → strength = min(1, 0.5 + |imbalance_5|)
  ├─ POTENTIAL_ABSORPTION (BUY): imbalance_20 > 0.35 AND delta < 0  → strength = 0.6
  └─ POTENTIAL_ABSORPTION (SELL): imbalance_20 < -0.35 AND delta > 0 → strength = 0.6
```

### Signal Generation (`app/signal.py`)

```
SignalEngine.decide(f, events)  [line 4]
  ├─ if no events or spread_bps <= 0 → Signal(NO_TRADE, 0, ...)
  ├─ buy = Σ(e.strength for BUY events); sell = Σ(e.strength for SELL events)
  ├─ if buy > sell AND buy >= 0.9 → Signal(BUY, min(1, buy/2), "order-flow alignment", ...)
  ├─ if sell > buy AND sell >= 0.9 → Signal(SELL, min(1, sell/2), "order-flow alignment", ...)
  └─ else → Signal(NO_TRADE, 0, "conflicting/weak flow", ...)
```

### Decision / Trade Orchestration (`app/orchestrator.py`)

```
TradeOrchestrator.decide(condition, notional_usd, book, equity, daily_pnl_pct, spread_bps) [line 42]
  ├─ line 48: if V5_BASELINE_NO_LIVE_TRADE → return {allowed: False, "governance": {blocked: True}}
  └─ line 60: else → return {allowed: False, "NOT_IMPLEMENTED"}
```

### Risk Engine (`app/risk.py`)

```
RiskEngine.pre_trade(equity, entry, stop, spread_bps, last_event_ms, now_ms, connected, new_notional, daily_pnl_pct, open_orders) [line 126]
  ├─ daily_loss_limit (0.05 * equity)
  ├─ spread_limit (50 bps)
  ├─ max_daily_trades
  ├─ drawdown_limit
  ├─ exposure_limit (50% equity)
  └─ cooldown
```

### Paper Execution (`app/execution.py`)

```
PaperExecution.submit(symbol, side, qty, price, client_id, book) [line 229]
  └─ SimulatedExchange.submit() [line 266] → fills at mid ± spread/2, taker fees
```

---

## 2. Canonical Strategy Identification

### FINDING: Two different signal-generation architectures exist.

**Architecture A — Production live path (`main.py`):**

| Component | File | Purpose |
|---|---|---|
| Signal engine | `app/signal.py` SignalEngine | Simple threshold-based; sums event strengths from EventDetector; fires BUY/SELL when sum >= 0.9 |
| Event detector | `app/events.py` EventDetector | Hardcoded thresholds: `delta > 0 & imbalance_5 > 0.20` (BUY), `delta < 0 & imbalance_5 < -0.20` (SELL), absorption at `imbalance_20 > ±0.35` |
| **NOT USED** | `app/decision.py` DecisionEngine | NOT instantiated in `main.py` |

**Architecture B — Research / paper-trading path:**

| Component | File | Purpose |
|---|---|---|
| V5 ridge model | `app/v5_model.py` (frozen in `data/research/v5_model.json`) | 17-feature frozen ridge regression predicting expected 500ms return |
| Decision engine | `app/decision.py` DecisionEngine | Loads V5 model + calibration; produces SignalDecision with calibrated expected return and cost gate |
| Used in | `run_paper_simulation.py`, `app/paper_runtime.py` `create_paper_engine()` | NOT the live `main.py` path |

**CONCLUSION (TASK 2):**

Answer: **C) Two different strategy implementations currently exist.**

- `SignalEngine` (Architecture A, `app/signal.py`) is the **canonical existing order-flow strategy** as implemented in the production live path (`main.py`).
- The V5 ridge model + `DecisionEngine` (Architecture B, `app/decision.py`) is a **separate research/paper-trading strategy** used in `run_paper_simulation.py` and `app/paper_runtime.py`.
- `main.py` does NOT import, instantiate, or call `DecisionEngine` at any point.
- `DecisionEngine.evaluate()` requires 17 V5 features that `OrderFlowEngine.snapshot()` does not produce (different feature set).

---

## 3. Research/Live Differences

| Aspect | Production (main.py) | Research (DecisionEngine/V5) |
|---|---|---|
| Signal source | `SignalEngine.decide()` — rule thresholds | V5 frozen ridge model prediction |
| Event detector | `EventDetector.detect()` — hardcoded thresholds | Not used |
| Input features | `delta`, `imbalance_5`, `imbalance_20`, `spread_bps`, `mid` | 17 V5 features (qi_l1, mpd_bps, di_l10, etc.) |
| Signal threshold | `strength >= 0.9` (composite of imbalance + delta) | `|calibrated_pred| > (taker_gate + safety_margin) = 5.17 bps` |
| Signal horizon | Implicit: `cond='delta_5s_top_decile'` (5s return used as label) | Explicit: 500ms |
| Cost gate | `orch.decide()` always returns `allowed=False` (governance) | `calibrated > 5.17 bps` for EXECUTION_READY |
| Direction | `delta > 0` (buy flow) → BUY; `delta < 0` → SELL | `calibrated > 0` → BUY; `calibrated < 0` → SELL |
| Normalization | Raw `imbalance_5`, `delta` (volume units) | Ridge coefficients on z-scored features |
| Execution path | `TradeOrchestrator` → always blocked | `DecisionEngine.evaluate()` → EXECUTION_READY |

---

## 4. Feature Inventory — Production SignalEngine Path

### Input features consumed by EventDetector + SignalEngine (from `OrderFlowEngine.snapshot()`):

| Feature | File:Line | Description |
|---|---|---|
| `delta` | `features.py:306` | Buy volume - sell volume over 5000ms rolling window |
| `imbalance_5` | `features.py:314` | `(bid_depth5 - ask_depth5) / (bid_depth5 + ask_depth5)` |
| `imbalance_20` | `features.py:315` | Same at 20 levels |
| `spread_bps` | `features.py:303` | `(best_ask - best_bid) / mid * 1e4` |
| `mid` | `features.py:304` | `(best_bid + best_ask) / 2` |

### Thresholds:

| Parameter | Value | Location |
|---|---|---|
| `imbalance_5` BUY threshold | `> 0.20` | `events.py:8` |
| `imbalance_5` SELL threshold | `< -0.20` | `events.py:9` |
| `imbalance_20` absorption (BUY) | `> 0.35` AND `delta < 0` | `events.py:10` |
| `imbalance_20` absorption (SELL) | `< -0.35` AND `delta > 0` | `events.py:11` |
| Signal strength minimum | `>= 0.9` | `signal.py:8-9` |
| Spread gate | `spread_bps > 0` | `signal.py:6` |
| Trade notional | `10,000 USD` | `main.py:38` |
| Cost gate | Always blocked (`V5_BASELINE_NO_LIVE_TRADE=True`) | `orchestrator.py:48-57` |

### Lookback/window:

| Component | Window | Location |
|---|---|---|
| `delta` (trade flow) | 5000ms rolling window | `features.py:116,460-465` |
| `imbalance_5` | Current book state (L5) | `features.py:314` |
| `imbalance_20` | Current book state (L20) | `features.py:315` |
| Signal evaluation frequency | Every depth/trade event (effectively ~continuous) | `main.py:34` |
| `snapshot()` call | Wall-clock `time.time()` fallback when no last event | `features.py:253-255` |

---

## 5. Causality Audit

### Production SignalEngine path (`main.py` → `features.py` → `events.py` → `signal.py`):

1. **`recv_ms` processing order**: The feed callback (`binance_feed.py:75-101`) processes WebSocket messages in arrival order. No sorting by exchange timestamp.

2. **`OrderFlowEngine.on_trade()` (`features.py:142`)**: Appends trade to `self.trades` with `t.ts_ms` (exchange trade time `T`). Trade buffer is pruned non-destructively in `_window_trades` using `now_ms` = wall-clock or last event time.

3. **`delta = _compute_delta(now)` (`features.py:306,460-465`)**: Sums buy/sell quantities in the last `window_ms` (5000ms) ending at `now`. Uses trade exchange timestamps (`t['ts_ms']`) for window membership, wall-clock for `now_ms`.

4. **`EventDetector.detect()` (`events.py`)**: Uses `f.delta` and `f.imbalance_5` — both computed from the current book state at event time.

5. **Causality assessment**:
   - `imbalance_5` and `imbalance_20` are computed from the **reconstructed book state at event time** — causal.
   - `delta` uses exchange trade timestamps (`T`) for window membership — causal.
   - `now_ms` defaults to `time.time()` when no last event exists — acceptable for live trading (wall-clock is the only available reference).
   - In historical replay, `recv_ms` from the raw log is used as the receive timestamp — causal.
   - **No look-ahead**: `snapshot()` reads only the current book state and trade history. No future data is accessed.
   - **No exchange-timestamp leakage**: Trade window membership uses `T` (exchange trade time), not `recv_ms`.

### DecisionEngine/V5 path (`decision.py`):

1. **`DecisionEngine.evaluate()` (`decision.py:103-293`)**:
   - Loads features from `FlowFeatures` → `vars(f)` (`decision.py:170-175`).
   - Requires 17 V5 features (`self.v5_features`, `decision.py:33`).
   - Calls `predict(model, df_feat, 500)` — uses frozen V5 model.
   - Calls `calibrate_prediction()` — uses binned calibration.

2. **Causality assessment**:
   - V5 model features are computed identically to the live `OrderFlowEngine` in terms of timing.
   - Calibration is fitted on train sessions only, applied identically to OOS.
   - **No look-ahead** in the model itself, but the calibrated predictions are severely compressed (max ~0.57 bps) so EXECUTION_READY is never reached.

---

## 6. Signal-Generation Audit

### Production SignalEngine path:

- **Signal type**: Binary rule-based (BUY/SELL/NO_TRADE)
- **Decision logic**: Sum event strengths; if buy > sell and buy >= 0.9 → BUY; symmetric for SELL
- **Strength formula**: `min(1, 0.5 + imbalance_5)` for flow events; fixed 0.6 for absorption events
- **Signal timing**: Evaluated on every depth update and trade event
- **Signal horizon**: No explicit prediction horizon. The `cond='delta_5s_top_decile'` parameter passed to `TradeOrchestrator.decide()` suggests a 5-second forward return is measured, but the signal itself is a contemporaneous snapshot.
- **No explicit hold duration or exit logic**: The `TradeOrchestrator.decide()` is supposed to handle this, but it always returns `allowed=False`.

### DecisionEngine/V5 path:

- **Signal type**: Calibrated expected return prediction (continuous, in bps)
- **Decision logic**: `calibrated = calibrate_prediction(raw_pred)`; if `|calibrated| > gate` → EXECUTION_READY
- **Signal timing**: Evaluated whenever `OrderFlowEngine.snapshot()` is called (typically per-event)
- **Signal horizon**: Explicitly 500ms (calibrated to the V5 model's training horizon)
- **Exit logic**: Not explicit — relies on continuous re-evaluation and position management

---

## 7. Historical Replay Results — Production SignalEngine Path

**Backtest parameters:**
- Sessions: 27 (all sessions in `data/live/v5/`)
- Horizon: 500ms (for P&L measurement, matching V5 for fair comparison)
- Cost gate: 4.6658 bps

**Signal counts:**

| Metric | Value |
|---|---|
| Total events processed | 57,161 (depth + trade events) |
| Signal events generated | 57,161 (one per event) |
| BUY signals | 6,932 |
| SELL signals | 14,385 |
| NO_TRADE signals | 35,844 |
| Traded signals (BUY+SELL) | 21,317 |
| Signal rate | 37.29% |

**P&L analysis (500ms horizon):**

| Metric | Value |
|---|---|
| Traded signals (with P&L) | 21,264 |
| Gross mean | 0.173638 bps |
| Net mean | -4.492162 bps |
| Execution cost gate | 4.6658 bps |
| t-statistic | 44.76 |
| p-value | 0.000000 |
| Block-bootstrap 95% CI (gross) | [0.130187, 0.218553] bps |
| Block-bootstrap 95% CI (net) | [-4.535613, -4.447247] bps |
| Median spread | 0.0155 bps |
| BUY gross | 0.183598 bps |
| SELL gross | 0.168834 bps |

**Performance by session (top 5 by gross):**

| Session | N | Gross (bps) | Net (bps) |
|---|---|---|---|
| 20260818-190823 | 856 | 0.5938 | -4.0720 |
| 20260818-214558 | 1867 | 0.3701 | -4.2957 |
| 20260818-212451 | 222 | 0.3500 | -4.3158 |
| 20260818-194015 | 1055 | 0.2049 | -4.4609 |
| 20260818-232223 | 833 | 0.1886 | -4.4772 |

**Performance by direction:**

| Direction | N | Gross (bps) | Net (bps) |
|---|---|---|---|
| BUY | 6,919 | 0.1836 | -4.4822 |
| SELL | 14,345 | 0.1688 | -4.4970 |

---

## 8. Cost Analysis

### Production path cost model:

| Cost component | Value | Source |
|---|---|---|
| Taker fee | 2.5 bps | `config.py` |
| Slippage | 0.5 bps | `config.py` |
| Safety margin | 0.5 bps | `config.py` |
| **Total round-trip gate** | **4.6658 bps** | `v5_cost.py:measured_gate()` |
| Spread (observed) | ~0.015 bps (median) | Negligible |

### V5 model calibrated cost gate:
- `DecisionEngine` gate = `taker_gate_bps (4.6658) + safety_margin_bps (0.5)` = **5.1658 bps**
- No production signal in the dataset reaches EXECUTION_READY (|calibrated| > 5.1658 bps = 0 signals)

### Adverse selection:
- Gross edge is positive but extremely small (0.17 bps for production, 0.095 bps for V5)
- Block-bootstrap CI is entirely above zero but far below the cost gate
- This represents a genuine but economically meaningless statistical edge

---

## 9. Statistical Validation

### Production SignalEngine path:

| Statistic | Value |
|---|---|
| Mean gross return | 0.173638 bps |
| Std dev | (computed from full distribution) |
| t-statistic | 44.76 |
| p-value | < 0.0001 |
| Block-bootstrap 95% CI | [0.130, 0.219] bps |
| n (traded signals) | 21,264 |
| Significance | Statistically significant (p << 0.05) |
| Economic viability | **NOT viable** (net = -4.49 bps vs gate = 4.67 bps) |

### V5 model (research path):

| Statistic | Value |
|---|---|
| Mean gross return (sign-based) | 0.095451 bps |
| t-statistic | 41.42 |
| p-value | < 0.0001 |
| Block-bootstrap 95% CI | [0.070, 0.120] bps |
| n (signals) | 49,897 |
| EXECUTION_READY count | 0 (no signal passes calibrated gate) |

### Stability across sessions:
- Production gross range: 0.000 to 0.594 bps (no session exceeds 0.6 bps)
- All sessions have net returns below -4.0 bps
- No session demonstrates economic viability
- The edge is statistically present but economically negligible

---

## 10. V5 vs Production-Path Comparison

| Metric | V5 Research | Production SignalEngine |
|---|---|---|
| Gross mean | 0.0955 bps | 0.1736 bps |
| Net mean | -4.5703 bps | -4.4922 bps |
| t-statistic | 41.42 | 44.76 |
| Block-bootstrap 95% CI | [0.070, 0.120] | [0.130, 0.219] |
| EXECUTION_READY signals | 0 | N/A (governance blocked) |
| Signal rate | ~100% (every event has prediction) | 37.29% |
| Directionality | Model-based (sign of calibrated) | Rule-based (delta + imbalance) |
| Horizon | 500ms (explicit) | Implicit (cond='delta_5s_top_decile') |

### Key finding:
- The production SignalEngine has a **higher gross edge** (0.17 bps vs 0.095 bps) but it is still **14x below the cost gate** (4.67 bps).
- The V5 model's calibrated predictions are compressed to a range that **never** produces EXECUTION_READY signals.
- Neither path is economically viable.
- The production SignalEngine fires significantly fewer signals (21,264 traded vs 49,897 for V5), with a higher signal-to-noise ratio.

### Model-selection bias note:
- We did NOT select the better-looking path. Both produce statistically significant but economically insufficient gross edges.
- The production path was not optimized for this backtest — we used the exact thresholds from `events.py` and `signal.py`.
- A model-selection bias analysis was not applicable because neither path was selected; both are measured independently.

---

## 11. Exact Files/Functions Changed

**No source files were modified during this audit.**

The backtest was performed by a standalone script `backtest_production.py` (not part of the application source tree). All production code remains unchanged.

---

## 12. Tests Executed

```
python3 -m pytest tests/ -v --tb=no -q
220 passed, 1 skipped in 43.59s
```

Existing tests include coverage for:
- `test_feature_parity.py` — research/live feature parity (22/22)
- `test_integration.py` — SignalEngine + EventDetector integration
- `test_decision.py` — DecisionEngine evaluation
- `test_safety_block.py` — V5_BASELINE_NO_LIVE_TRADE governance enforcement
- `test_v5_evidence.py` — V5 OOS evaluation
- `test_replay.py` — replay engine integration

---

## 13. Final Production Verdict

### VERDICT: **#2 — PRODUCTION PATH VALIDATED

**PRODUCTION PATH VALIDATED — statistically predictive but economically insufficient.**

### Summary:

1. **Call graph traced**: The production live path (`main.py`) uses `SignalEngine` + `EventDetector` with hardcoded thresholds. The V5 model + `DecisionEngine` is NOT part of the live path — it only exists in `paper_runtime.py` and `run_paper_simulation.py`.

2. **Duplication identified (TASK 2 — Option C)**: Two signal-generation architectures exist. The production path uses rule-based thresholds; the research path uses a frozen V5 ridge model. They are not reconciled — `main.py` does not use `DecisionEngine`.

3. **Causality audit passed**: No look-ahead, no exchange-timestamp leakage. Trade window membership uses `T` (exchange time); `now_ms` falls back to wall-clock only when no exchange event exists.

4. **Production backtest completed**:
   - 57,161 events processed across 27 sessions
   - 21,264 traded signals (6,932 BUY + 14,352 SELL)
   - Gross edge: 0.174 bps (statistically significant, p < 0.0001)
   - Net after cost gate (4.67 bps): -4.49 bps
   - Block-bootstrap 95% CI: [0.130, 0.219] bps (gross) — does not overlap the cost gate

5. **Comparison**: V5 gross = 0.095 bps, Production gross = 0.174 bps — both far below the 4.67 bps gate. V5 EXECUTION_READY count = 0.

6. **No parameters were tuned, optimized, or fished.** All thresholds, the V5 model, the calibration, the cost gate, and the signal horizon were used unchanged.

### Recommendation:

- **KEEP `V5_BASELINE_NO_LIVE_TRADE = TRUE`** — the production SignalEngine demonstrates a statistically significant but economically insufficient signal (gross 0.17 bps vs gate 4.67 bps). The V5 model path produces zero EXECUTION_READY signals.
- **Reconciliation required**: The production `main.py` path and the research `DecisionEngine`/`V5` path are different implementations. If the V5 model is intended to be the canonical strategy, `main.py` should be updated to use `DecisionEngine` instead of `SignalEngine`. This is an architectural decision that must be made before further validation.
- No live trading or order placement should occur with either path.
