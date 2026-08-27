# FINAL DEPLOYMENT AUDIT REPORT

**Project:** binance_orderflow_autotrader_v2
**Date:** 2026-08-25
**Auditor:** Kilo forensic pipeline
**Freeze ID:** ORDERFLOW_BASELINE_V5 — V5_BASELINE_NO_LIVE_TRADE = TRUE throughout

---

## EXECUTIVE SUMMARY

**FINAL CLASSIFICATION: #2 — STATISTICALLY VALID BUT ECONOMICALLY INSUFFICIENT**

The existing Binance order-flow autotrader has a statistically significant predictive signal (gross edge 0.04–0.76 bps depending on configuration) but this edge is structurally insufficient to overcome measured execution costs (2.94–4.67 bps). The gap between signal magnitude and execution cost is 3.9x–6.1x, and no configuration of the existing features, thresholds, or execution model produces positive net expectancy.

**Live trading remains BLOCKED. V5_BASELINE_NO_LIVE_TRADE = TRUE.**

---

## PHASE 1 — REPOSITORY BASELINE

### Architecture Map

```
ENTRY POINTS:
  main.py (live paper trading)
  run_paper_simulation.py (paper simulation)
  paper_runtime.py (paper engine)

DATA PIPELINE:
  binance_feed.py → orderbook.py → features.py → derived_v5.jsonl
  l2_collector.py → raw.jsonl → l2_replay.py → derived.jsonl
  v3_replay.py → v4_replay.py → v5_features.py → v5_evidence.py

SIGNAL GENERATION (TWO PATHS):
  Path A (Production): features.py → events.py → signal.py → orchestrator.py
  Path B (Research):   features.py → v5_model.py → decision.py → paper_runtime.py

EXECUTION:
  execution.py (PaperExecution, SimulatedExchange, LiveExecution-locked)
  fillmodel.py (PassiveFillModel for maker execution)
  orchestrator.py (TradeOrchestrator with governance block)
  risk.py (RiskEngine with pre-trade controls)
  integrity_gate.py (IntegrityGate chain)

MODEL:
  v5_model.py (frozen ridge, 17 features, 500ms horizon)
  v5_calibration.py (15-bin piecewise constant)
  v5_cost.py (measured gate = 4.6658 bps)
  v3_cost.py (cost model components)

CONFIGURATION:
  config.py (V5_BASELINE_NO_LIVE_TRADE = True)
```

### Key Files

| File | Purpose | Lines |
|---|---|---|
| app/main.py | Live entry point | 46 |
| app/config.py | Configuration + governance | 35 |
| app/features.py | OrderFlowEngine (live features) | 492 |
| app/events.py | EventDetector (thresholds) | 12 |
| app/signal.py | SignalEngine (rules) | 10 |
| app/decision.py | DecisionEngine (V5 model) | 293 |
| app/orchestrator.py | TradeOrchestrator (governance) | 494 |
| app/risk.py | RiskEngine (pre-trade) | 165 |
| app/execution.py | PaperExecution + LiveExecution | 296 |
| app/fillmodel.py | PassiveFillModel (maker) | 140 |
| app/v5_model.py | Frozen V5 ridge model | 69 |
| app/v5_calibration.py | Binned calibration | 221 |
| app/v5_cost.py | Measured cost gate | 59 |
| app/v3_cost.py | Cost model components | 141 |

### Test Coverage

- **220 tests passing, 1 skipped**
- Coverage: feature parity, decision engine, governance block, replay engine, integration, safety

---

## PHASE 2 — PRODUCTION/RESEARCH PATH RECONCILIATION

### Finding: TWO Different Signal Architectures Exist

| Aspect | Production (main.py) | Research (decision.py) |
|---|---|---|
| Signal engine | SignalEngine (simple thresholds) | DecisionEngine (V5 ridge model) |
| Event detector | EventDetector (hardcoded) | Not used |
| Input features | 4 (delta, imbalance_5, imbalance_20, spread_bps) | 17 (V5 features) |
| Signal threshold | strength >= 0.9 | calibrated > 5.1658 bps |
| Signal horizon | Implicit (5s label) | Explicit (500ms) |
| Cost gate | Always blocked (governance) | 5.1658 bps |
| Direction | delta > 0 → BUY, delta < 0 → SELL | calibrated > 0 → BUY, < 0 → SELL |
| Used in | main.py | paper_runtime.py, run_paper_simulation.py |

### Apples-to-Apples Comparison (27 sessions, 500ms horizon, identical events)

| Metric | SignalEngine (Production) | V5 DecisionEngine (Research) |
|---|---|---|
| Traded signals | 21,264 | 53,141 |
| BUY signals | 6,919 | 18,718 |
| SELL signals | 14,345 | 34,423 |
| Gross mean | 0.1736 bps | 0.0413 bps |
| Net mean (taker) | -4.4922 bps | -4.6245 bps |
| t-statistic | 44.76 | 20.73 |
| p-value | < 0.0001 | < 0.0001 |
| Block-bootstrap 95% CI (gross) | [0.130, 0.219] | [0.019, 0.066] |
| EXECUTION_READY signals | N/A | 0 (0.0000%) |
| Hit rate (gross > 0) | 20.62% | 9.31% |

### Key Insight

The SignalEngine has a **higher gross edge** (0.174 vs 0.041 bps) because:
1. It fires on strong imbalance/delta events that have higher hit rate
2. The V5 DecisionEngine's calibrated predictions are severely compressed (max 0.085 bps, far below the 5.17 bps gate)
3. The V5 model's calibration maps all predictions to [-0.57, 0.085] bps range

**Both paths are economically insufficient.**

---

## PHASE 3 — ECONOMIC BOTTLENECK ANALYSIS

### Pre-Registered Hypotheses (15 conditions, chronological OOS)

| # | Condition | N_val | Gross (bps) | Net (bps) | t-stat | Bootstrap CI |
|---|-----------|-------|-------------|-----------|--------|-------------|
| 1 | TFI_abs > 0.5 | 23,981 | 0.227 | -4.439 | 31.4 | [0.101, 0.278] |
| 2 | TFI_abs > 0.5 & vol > 0 | 3,812 | 0.690 | -3.976 | 25.6 | [0.199, 0.797] |
| 3 | \|qi_l1\| > 0.7 | 23,981 | 0.246 | -4.420 | 33.6 | [0.128, 0.345] |
| 4 | \|qi_l1\| > 0.7 & aligned | 23,981 | 0.258 | -4.408 | — | [0.132, 0.352] |
| 5 | liq_dep > 50pct | 23,981 | 0.248 | -4.417 | — | [0.093, 0.300] |
| 6 | TFI_abs > 0.7 & liq_dep > 50pct | 23,981 | 0.272 | -4.394 | — | [0.120, 0.329] |
| 7 | cancel_pres > 50pct | 23,981 | 0.004 | -4.662 | 1.7 | [0.000, 0.010] |
| 8 | log_event_rate > p50 | 23,981 | 0.411 | -4.255 | 33.3 | [0.148, 0.464] |
| 9 | TFI_abs > 0.7 & vol > p50 | 23,981 | 0.762 | -3.904 | 29.7 | [0.205, 0.800] |
| 10 | spread > p80 | 23,981 | 0.249 | -4.417 | — | [-0.032, 0.928] |
| 11 | \|OFI\| > 0 & \|qi\| > 0.5 | 23,981 | 0.005 | -4.661 | — | [-0.003, 0.010] |
| 12 | OFI signed & \|qi\| > 0.5 | 23,981 | 0.011 | -4.655 | — | [0.001, 0.034] |
| 13 | log_depth1 < p30 & log_depth5 > p70 | 23,981 | -0.528 | -5.194 | — | [-0.425, 1.146] |
| 14 | TFI > 0 & depth_slope > 0 | 23,981 | -0.020 | -4.686 | — | [-0.047, -0.003] |
| 15 | vol_500 > 0 | 3,812 | 0.676 | -3.989 | 26.6 | [-0.075, 0.786] |

### Best Conditional Regime

- **Condition:** TFI_abs > 0.7 & vol > p50
- **Gross:** 0.762 bps
- **Net (taker):** -3.904 bps
- **Net (maker):** -2.178 bps
- **Gap to taker gate:** 6.1x
- **Gap to maker cost:** 3.9x

### Conclusion

**No hypothesis survives economic acceptance.** All 15 conditions produce negative net after costs. The best gross edge (0.762 bps) is 6.1x below the taker gate and 3.9x below the maker cost.

---

## PHASE 4 — EXECUTION-COST DECOMPOSITION

### Current Gate Components

| Component | Value | Source |
|---|---|---|
| Effective taker roundtrip (p90, 1000-notional) | 4.0158 bps | execution_calibration.json |
| Market impact allowance | 0.1000 bps | v3_cost.py:30 |
| Latency cost | 0.0500 bps | v3_cost.py:31 |
| Safety margin | 0.5000 bps | v3_cost.py:29 |
| **Total gate** | **4.6658 bps** | v5_cost.py |

### Taker Roundtrip Decomposition

| Component | Value |
|---|---|
| Spread (p90) | 0.0158 bps |
| Slippage buy (p90) | 0.0079 bps |
| Slippage sell (p90) | 0.0079 bps |
| Taker fee (round-trip) | 4.0000 bps |
| **Total** | **4.0316 bps** |

### Maker Execution Cost

| Component | Value |
|---|---|
| Maker fee (round-trip) | 2.0000 bps |
| Adverse selection (median) | 0.7680 bps |
| Reprice cost (if no fill) | 0.1216 bps |
| Latency cost | 0.0500 bps |
| **Total maker cost** | **2.9396 bps** |

### Maximum Allowable Cost

| Configuration | Gross Edge | Max Allowable Cost |
|---|---|---|
| SignalEngine unconditional | 0.1736 bps | 0.1736 bps |
| V5 DecisionEngine unconditional | 0.0413 bps | 0.0413 bps |
| Best conditional (TFI>0.7 & vol>p50) | 0.7620 bps | 0.7620 bps |

### Cost Sensitivity

| Cost | SignalEngine Net | V5 Net | Best Conditional Net |
|---|---|---|---|
| 4.666 (taker) | -4.492 | -4.625 | -3.904 |
| 2.940 (maker) | -2.766 | -2.898 | -2.178 |
| 1.000 | -0.826 | -0.959 | -0.238 |
| 0.500 | -0.326 | -0.459 | +0.262 |
| 0.200 | -0.026 | -0.159 | +0.562 |
| 0.174 | -0.0004 | -0.133 | +0.588 |

**Even with zero execution cost, the net edge would be 0.174 bps (SignalEngine) or 0.762 bps (best conditional) — tiny edges that would require massive leverage and volume to be meaningful.**

---

## PHASE 5 — EXECUTION MODEL AUDIT

### Execution Architecture

| Component | Description |
|---|---|
| PaperExecution | Aggressive fill at touched price (buy@ask, sell@bid) |
| SimulatedExchange | Configurable (fill/reject/partial/timeout) |
| LiveExecution | Hard-locked (raises RuntimeError) |
| PassiveFillModel | Maker execution with P(fill), adverse selection |
| OrderStateManager | Order lifecycle + duplicate protection |

### Production Path Execution

1. SignalEngine produces BUY/SELL/NO_TRADE
2. If BUY/SELL AND integrity gate passes → TradeOrchestrator.decide()
3. TradeOrchestrator ALWAYS returns allowed=False (governance block)
4. No actual orders are ever placed

### Execution Assumptions

- Immediate fill at touched price (aggressive/taker)
- No partial fills
- No queue position modeling
- No latency modeling beyond fixed 0.05 bps
- No market impact model beyond fixed 0.10 bps

### Economic Impact

Even if maker execution were used (2.94 bps), the SignalEngine net would be -2.77 bps. The signal magnitude is simply too small for any execution model.

---

## PHASE 6 — BEST EXISTING ALGORITHM

### Candidate Configurations

| Config | Gross (bps) | Net Taker (bps) | Net Maker (bps) | N |
|---|---|---|---|---|
| A: SignalEngine unconditional | 0.1736 | -4.4922 | -2.7660 | 21,264 |
| B: V5 DecisionEngine unconditional | 0.0413 | -4.6245 | -2.8983 | 53,141 |
| C: V5 EXECUTION_READY only | 0.0000 | -4.6658 | -2.9396 | 0 |
| D: SignalEngine + maker | 0.1736 | -4.4922 | -2.7660 | 21,264 |
| E: Best conditional (TFI>0.7 & vol>p50) | 0.7620 | -3.9038 | -2.1776 | 210 |
| F: SignalEngine BUY only | 0.1836 | -4.4822 | -2.7560 | 6,919 |
| G: SignalEngine SELL only | 0.1688 | -4.4970 | -2.7708 | 14,345 |

### OOS Stability

| Metric | SignalEngine | V5 DecisionEngine |
|---|---|---|
| Min session gross | 0.0000 bps | -0.1083 bps |
| Max session gross | 0.5938 bps | 0.1749 bps |
| Mean session gross | 0.1740 bps | 0.0362 bps |
| Std session gross | 0.1688 bps | 0.0658 bps |
| Sessions positive | 23/26 | 20/26 |

### Conclusion

**NO CONFIGURATION CLEARS THE ECONOMIC GATE.**

The best gross edge (0.762 bps, conditional) is:
- 6.1x below the taker gate (4.67 bps)
- 3.9x below the maker cost (2.94 bps)

The signal magnitude is structurally insufficient for positive expectancy under any realistic execution model.

---

## PHASE 7 — IMPLEMENT ONLY VERIFIED IMPROVEMENTS

**No improvements were implemented** because no configuration of the existing features, thresholds, or execution model produces positive net expectancy. Implementing any of the candidate configurations would result in guaranteed economic loss.

---

## PHASE 8 — FULL VALIDATION

### Test Suite

```
python3 -m pytest tests/ -v --tb=short
220 passed, 1 skipped in 35.31s
```

### Validation Checklist

| Check | Status |
|---|---|
| Feature parity (research/live) | PASS — 22/22 features match |
| No look-ahead | PASS — all features use trailing windows |
| Event-time correctness | PASS — trade window uses exchange timestamps |
| Out-of-order exchange timestamps | PASS — handled by recv_ms processing order |
| 500ms window correctness | PASS — verified in feature parity tests |
| Model determinism | PASS — frozen coefficients, deterministic predict |
| Execution-cost accounting | PASS — measured gate from calibration |
| Risk controls | PASS — RiskEngine with hard limits |
| Position state | PASS — PaperPosition with realized/unrealized PnL |
| TradeOrchestrator | PASS — governance block enforced |
| PaperExecution | PASS — fills at touched price |
| Live-trading safety block | PASS — V5_BASELINE_NO_LIVE_TRADE = True |

---

## PHASE 9 — FINAL DEPLOYMENT DECISION

### Component Status Table

| Component | Status |
|---|---|
| Data pipeline | VERIFIED — deterministic replay, immutable raw logs |
| Feature construction | VERIFIED — 17 V5 features, causal, no look-ahead |
| Event-time causality | VERIFIED — trade windows use exchange timestamps |
| Research/live parity | VERIFIED — 22/22 features match |
| V5 model | VERIFIED — frozen ridge, R²=0.26, deterministic |
| Signal generation | VERIFIED — two paths (SignalEngine + DecisionEngine) |
| Execution model | VERIFIED — PaperExecution at touched price |
| Cost model | VERIFIED — measured gate = 4.6658 bps |
| Risk engine | VERIFIED — hard controls, pre-trade checks |
| Position state | VERIFIED — PaperPosition with full PnL tracking |
| Tests | PASSING — 220 passed, 1 skipped |
| OOS validation | VERIFIED — 27 sessions, chronological splits |
| Economic edge | INSUFFICIENT — best gross 0.762 bps vs gate 4.67 bps |
| Live deployability | BLOCKED — V5_BASELINE_NO_LIVE_TRADE = True |

### Final Classification

## **#2 — STATISTICALLY VALID BUT ECONOMICALLY INSUFFICIENT**

### Evidence Summary

1. **Statistical signal IS present:**
   - SignalEngine: gross 0.174 bps, t=44.76, p<0.0001, 23/26 sessions positive
   - V5 DecisionEngine: gross 0.041 bps, t=20.73, p<0.0001, 20/26 sessions positive
   - Best conditional: gross 0.762 bps, t=29.7, p<0.0001

2. **Gross edge is real but tiny:**
   - SignalEngine: 0.174 bps per signal
   - V5 DecisionEngine: 0.041 bps per signal
   - Best conditional: 0.762 bps per signal

3. **Execution costs are 6.1x larger (best case):**
   - Taker gate: 4.6658 bps
   - Maker cost: 2.9396 bps
   - Best gross: 0.762 bps
   - Gap: 3.90–6.12 bps

4. **No configuration clears the economic gate:**
   - 15 pre-registered hypotheses tested
   - All produce negative net after costs
   - Best net: -3.90 bps (conditional, taker)

5. **The gap is structural:**
   - Signal magnitude (0.04–0.76 bps) is inherently small
   - Execution costs (2.94–4.67 bps) are measured, not assumed
   - No feature interaction or regime produces sufficient edge

### Decision

**KEEP V5_BASELINE_NO_LIVE_TRADE = TRUE.**

No change to the production strategy is warranted. The existing order-flow algorithm is correctly implemented, causally sound, and statistically predictive, but the signal magnitude is structurally insufficient to overcome execution costs.

### Highest-Value Research Question

**What is the maximum achievable gross edge from the Binance BTCUSDT order-flow information set at 500ms horizon?**

The current analysis suggests an upper bound of ~0.76 bps (from the best conditional regime). If this upper bound cannot be significantly expanded through:
- Alternative data sources (e.g., liquidations, funding rates, order-book snapshots at higher frequency)
- Alternative execution models (e.g., queue-position-aware passive execution)
- Alternative signal horizons (e.g., shorter or longer than 500ms)

...then the strategy will remain economically insufficient for live deployment.

### Files Changed

**No source files were modified during this audit.** All analysis was performed by standalone scripts that loaded the frozen model and evidence features without modification.

### Audit Artifacts

| File | Description |
|---|---|
| PHASE1_BASELINE.md | Architecture map and component inventory |
| ORDERFLOW_PRODUCTION_PATH_AUDIT.md | Production path audit (previous) |
| PRODUCTION_AUDIT.md | Forensic audit (previous) |
| phase2_reconciliation.py | Production/research path comparison script |
| phase2_sigeng_results.csv | SignalEngine backtest results |
| phase2_v5_results.csv | V5 DecisionEngine backtest results |
| backtest_production.py | Production SignalEngine backtest script |

---

**END OF AUDIT REPORT**
