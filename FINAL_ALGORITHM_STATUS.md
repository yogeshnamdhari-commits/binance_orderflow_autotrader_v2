# FINAL ALGORITHM STATUS

**Date:** 2026-08-26
**Project:** binance_orderflow_autotrader_v2
**Classification:** **ECONOMICALLY INSUFFICIENT**

---

## A. CURRENT BASELINE

| Component | Status | Value |
|---|---|---|
| Tests | PASSING | 220 passed, 1 skipped |
| Feature parity | VERIFIED | 22/22 features match |
| Production SignalEngine gross | +0.174 bps | t=44.76, p<0.0001 |
| V5 DecisionEngine gross | +0.041 bps | t=20.73, p<0.0001 |
| Best conditional gross | +0.762 bps | TFI>0.7 & vol>p50 |
| Best horizon gross | +0.280 bps | 30s horizon |
| Maker cost | 2.0 bps | Measured |
| Taker cost | 4.666 bps | Measured |
| Net edge | NEGATIVE | All configurations |

---

## B. HYPOTHESES TESTED

| ID | Name | Research Basis | OOS Gross (bps) | p-value | Net Maker (bps) | Pass |
|---|---|---|---|---|---|---|
| A | Order Flow Toxicity (VPIN) | Easley et al. (2012) | N/A (insufficient signals) | — | — | NO |
| B | Multi-Level Imbalance | Cont et al. (2014) | 0.004 | 0.604 | -1.996 | NO |
| C | Size-Weighted Flow | Chordia et al. (2002) | 0.367 | <0.0001 | -1.633 | NO |

**Bonferroni-corrected α = 0.0167**

---

## C. RESEARCH BASIS

### Hypothesis A: Order Flow Toxicity (VPIN)
- **Paper:** Easley, Lopez de Prado, O'Hara (2012) "Flow Toxicity and Liquidity in a High-Frequency World"
- **Mechanism:** Volume-synchronized probability of informed trading predicts short-term reversals
- **Result:** Insufficient signals for evaluation (VPIN proxy using |tfi_500| did not yield enough data points)

### Hypothesis B: Multi-Level Book Imbalance Interaction
- **Paper:** Cont, Kukanov, Stoikov (2014) "Price Impact of Order Book Events"
- **Mechanism:** Interaction between L1 and L5 imbalance captures depth resilience
- **Result:** Gross = 0.004 bps (not significant, p=0.604). The interaction term adds no incremental predictive power.

### Hypothesis C: Trade Size-Weighted Flow Imbalance
- **Paper:** Chordia, Subrahmanyam, Roll (2002) "Order Imbalance, Liquidity, and Market Returns"
- **Mechanism:** Large trades have more information content than small trades
- **Result:** Gross = 0.367 bps (significant, p<0.0001). Highest gross edge but still 5.4x below maker cost.

---

## D. OOS RESULTS

### Evaluation Protocol
- Chronological split: 13 train / 9 OOS sessions
- OOS events: 21,881
- Horizon: 500ms
- No parameter tuning after seeing results

### Detailed Results

#### Hypothesis B: Multi-Level Imbalance Interaction
| Metric | Value |
|---|---|
| Signals | 13,215 |
| Gross | 0.004 bps |
| 95% CI | [-0.077, 0.095] |
| p-value | 0.604 |
| Net (maker) | -1.996 bps |
| Sessions positive | 3/9 |

#### Hypothesis C: Size-Weighted Flow
| Metric | Value |
|---|---|
| Signals | 5,976 |
| Gross | 0.367 bps |
| 95% CI | [0.247, 0.501] |
| p-value | < 0.0001 |
| Net (maker) | -1.633 bps |
| Sessions positive | 7/9 |

---

## E. NET EDGE AFTER COSTS

| Configuration | Gross (bps) | Net Maker (bps) | Net Taker (bps) |
|---|---|---|---|
| Current baseline (SignalEngine) | 0.174 | -1.826 | -4.492 |
| Current baseline (V5) | 0.041 | -1.959 | -4.625 |
| Best hypothesis (C: Size-Weighted) | 0.367 | -1.633 | -4.299 |
| Best conditional (TFI>0.7 & vol>p50) | 0.762 | -2.178 | -3.904 |
| Best horizon (30s) | 0.280 | -1.720 | -3.736 |

**No configuration produces positive net expectancy.**

---

## F. STATISTICAL SIGNIFICANCE

| Configuration | t-stat | p-value | Significant (α=0.0167) |
|---|---|---|---|
| Current SignalEngine | 44.76 | <0.0001 | YES |
| Current V5 | 20.73 | <0.0001 | YES |
| Hypothesis C | 34.68 | <0.0001 | YES |
| Hypothesis B | 0.52 | 0.604 | NO |

All statistically significant configurations have **negative net edge** after execution costs.

---

## G. ROBUSTNESS RESULTS

### Session Stability
| Configuration | Sessions Positive | Total Sessions |
|---|---|---|
| SignalEngine | 23/26 | 88.5% |
| V5 | 20/26 | 76.9% |
| Hypothesis C | 7/9 | 77.8% |
| Hypothesis B | 3/9 | 33.3% |

### Permutation Control
- Signal direction permutation eliminates the edge at long horizons (>10s)
- Confirms signal captures short-term mean-reversion, not trend

### Horizon Analysis
- Edge peaks at 30s (0.280 bps) but with higher volatility
- Signal direction HURTS at >10s (mean-reversion characteristic)
- No horizon produces economically viable edge

---

## H. EXACT FILES CHANGED

**No production source files were modified during this research phase.**

All analysis was performed by standalone scripts:
- `phase4_oos_validation.py` — OOS validation script
- `RESEARCH_HYPOTHESES.md` — Pre-registered hypotheses
- `FROZEN_BASELINE.md` — Frozen baseline documentation

---

## I. EXACT TESTS PASSED

```
220 passed, 1 skipped in 55.71s
```

All existing tests continue to pass. No production code was modified.

---

## J. FINAL CLASSIFICATION

### **ECONOMICALLY INSUFFICIENT**

### Reasoning

1. **All 3 pre-registered hypotheses fail the economic gate:**
   - Hypothesis A: Insufficient signals
   - Hypothesis B: Not statistically significant (p=0.604)
   - Hypothesis C: Statistically significant but net edge = -1.633 bps

2. **The signal magnitude bottleneck is structural:**
   - Best gross edge: 0.762 bps (conditional) or 0.367 bps (hypothesis C)
   - Maker cost: 2.0 bps
   - Gap: 1.2–1.8 bps (cannot be closed by feature engineering alone)

3. **The gap cannot be closed by:**
   - Feature engineering (tested 3 research-backed hypotheses)
   - Horizon extension (best 30s = 0.280 bps)
   - Execution optimization (best maker = 2.0 bps cost)
   - Conditional filtering (best = 0.762 bps)

4. **The information set is insufficient:**
   - Current order-flow features capture genuine but tiny predictive information
   - The signal is statistically significant but economically meaningless
   - To achieve viability, the signal magnitude would need to increase by ~6x

### Decision

**DO NOT modify production.**
**Keep V5_BASELINE_NO_LIVE_TRADE = True.**
**Live trading remains BLOCKED.**

### Highest-Value Research Question

**What additional information (beyond the current order-flow features) is required to increase the gross edge from ~0.17 bps to >2.0 bps?**

The current BTCUSDT order-flow information set (OFI, TFI, queue imbalance, depth imbalance, etc.) does not contain enough predictive information to overcome execution costs at any horizon from 100ms to 60s.

Potential directions (not implemented):
- Alternative data sources (liquidations, funding rates, cross-market signals)
- Higher-frequency data (sub-100ms resolution)
- Cross-asset information (correlated assets, spot-futures basis)
- Queue-position-aware execution modeling

---

## APPENDIX: COMPLETE AUDIT TRAIL

| Audit | Date | Classification |
|---|---|---|
| Production Path Audit | 2026-08-25 | #2 — Statistically valid but economically insufficient |
| Execution Economic Audit | 2026-08-25 | C — Insufficient even with execution improvements |
| Horizon Economic Audit | 2026-08-25 | B — Predictive but insufficient at all horizons |
| Phase 4 OOS Validation | 2026-08-26 | ECONOMICALLY INSUFFICIENT |

---

**END OF FINAL ALGORITHM STATUS**
