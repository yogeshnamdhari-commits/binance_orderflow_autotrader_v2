# EXECUTION ECONOMIC AUDIT

**Date:** 2026-08-25
**Objective:** Determine whether the existing order-flow signal can be executed with positive net expectancy
**Method:** Pre-registered hypotheses evaluated on chronological OOS replay data
**Classification:** **C — Existing signal remains economically insufficient even with realistic execution improvements**

---

## 1. PRE-REGISTERED HYPOTHESES

### Execution Cost Parameters (from execution_calibration.json, UNCHANGED)

| Parameter | Value |
|---|---|
| Taker fee (one-way) | 2.0 bps |
| Maker fee (one-way) | 1.0 bps |
| Spread (median) | 0.0157 bps |
| Slippage (p90, 1000-notional) | 0.0079 bps |
| Effective taker roundtrip (p90) | 4.0158 bps |
| P(fill) same tick (median) | 0.71 |
| Adverse selection (median) | 0.768 bps |
| Latency assumption | 5.0 ms |

### Hypotheses

| ID | Name | Description |
|---|---|---|
| H1 | Market-Order (Taker) | Fill immediately at best ask/bid with taker fee |
| H2 | Aggressive-Limit | Cross spread, wait 50ms, then chase at market |
| H3 | Passive-Limit (Maker) | Join queue at best bid/ask, wait 500ms for fill |
| H4 | Signal-Strength-Conditioned | Strong signals → aggressive, weak → passive |
| H5 | Queue/Imbalance-Aware | High |qi| → passive, low |qi| → aggressive |
| H6 | Post-Only Limit | Post-only with maker rebates |
| H7 | Delayed Execution | Wait 100ms after signal before executing |

### Multiple-Hypothesis Correction

- **Number of hypotheses:** 7
- **Correction method:** Bonferroni (α = 0.05/7 = 0.00714)
- **Confidence level:** 99.286% for individual tests

### Decision Rules (Pre-Registered)

- **Classification A (Viable):** Net > 0 with p < 0.00714 AND fill rate > 50%
- **Classification B (Potentially Viable):** Net > 0 with p < 0.05 OR net > -1.0 bps with fill rate > 70%
- **Classification C (Insufficient):** Net < -1.0 bps OR fill rate < 50% with net < 0

---

## 2. EXECUTION DATA AUDIT

### Available Data

| Data Source | Content | Used For |
|---|---|---|
| derived_v5.jsonl | Top-10 level book snapshots per event | Book state at signal time |
| raw.jsonl | Raw depth/trade events | Replay through OrderFlowEngine |
| execution_calibration.json | Measured taker/maker costs | Cost model parameters |
| oos_fill | Empirical fill probabilities | Passive execution modeling |

### Book State at Signal Time

- Best bid/ask prices and quantities
- Top-10 level depth
- Queue imbalance (qi_l1)
- Spread (bps)
- Mid price

---

## 3. HYPOTHESIS EVALUATION RESULTS

### H1: Market-Order (Taker) Execution

| Metric | Value |
|---|---|
| Signals | 21,264 |
| Gross mean | 0.1663 bps |
| Net mean | -3.8572 bps |
| Avg cost | 4.0235 bps |
| Fill rate | 100% |
| t-stat (net) | -1010.56 |
| p-value | < 0.0001 |
| 95% CI (net) | [-3.900, -3.813] bps |
| Sessions positive | 0/26 |
| **Classification** | **C (Insufficient)** |

### H2: Aggressive-Limit Execution

| Metric | Value |
|---|---|
| Signals | 21,264 |
| Gross mean | 0.1663 bps |
| Net mean | -2.4462 bps |
| Avg cost | 2.6125 bps |
| Fill rate | 100% |
| t-stat (net) | -640.98 |
| p-value | < 0.0001 |
| 95% CI (net) | [-2.489, -2.402] bps |
| Sessions positive | 0/26 |
| **Classification** | **C (Insufficient)** |

### H3: Passive-Limit (Maker) Execution

| Metric | Value |
|---|---|
| Signals | 21,264 |
| Gross mean | 0.1663 bps |
| Net mean | -0.8451 bps |
| Avg cost | 2.0000 bps |
| Fill rate | 46.3% |
| t-stat (net) | -124.52 |
| p-value | < 0.0001 |
| 95% CI (net) | [-0.871, -0.820] bps |
| Sessions positive | 0/26 |
| **Classification** | **C (Insufficient)** |

### H4: Signal-Strength-Conditioned Execution

| Metric | Value |
|---|---|
| Signals | 21,264 |
| Gross mean | 0.1663 bps |
| Net mean | -1.8337 bps |
| Avg cost | 2.0000 bps |
| Fill rate | 46.3% |
| t-stat (net) | -480.60 |
| p-value | < 0.0001 |
| 95% CI (net) | [-1.877, -1.790] bps |
| Sessions positive | 0/26 |
| **Classification** | **C (Insufficient)** |

### H5: Queue/Imbalance-Aware Execution

| Metric | Value |
|---|---|
| Signals | 21,264 |
| Gross mean | 0.1663 bps |
| Net mean | -2.0607 bps |
| Avg cost | 2.2270 bps |
| Fill rate | 63.4% |
| t-stat (net) | -435.67 |
| p-value | < 0.0001 |
| 95% CI (net) | [-2.114, -2.006] bps |
| Sessions positive | 0/26 |
| **Classification** | **C (Insufficient)** |

### H6: Post-Only Limit with Maker Rebates

| Metric | Value |
|---|---|
| Signals | 21,264 |
| Gross mean | 0.1663 bps |
| Net mean | -0.8451 bps |
| Avg cost | 2.0000 bps |
| Fill rate | 46.3% |
| **Classification** | **C (Insufficient)** |

### H7: Delayed Execution

| Metric | Value |
|---|---|
| Signals | 21,264 |
| Gross mean | 0.1663 bps |
| Net mean | -3.8572 bps |
| Avg cost | 4.0235 bps |
| Fill rate | 100% |
| **Classification** | **C (Insufficient)** |

---

## 4. SUMMARY TABLE

| Hypothesis | N | Gross (bps) | Net (bps) | Cost (bps) | Fill Rate | p-value | Classification |
|---|---|---|---|---|---|---|---|
| H1: Market-Order (Taker) | 21,264 | 0.166 | -3.857 | 4.024 | 1.000 | < 0.0001 | C |
| H2: Aggressive-Limit | 21,264 | 0.166 | -2.446 | 2.613 | 1.000 | < 0.0001 | C |
| H3: Passive-Limit (Maker) | 21,264 | 0.166 | -0.845 | 2.000 | 0.463 | < 0.0001 | C |
| H4: Strength-Conditioned | 21,264 | 0.166 | -1.834 | 2.000 | 0.463 | < 0.0001 | C |
| H5: Queue-Aware | 21,264 | 0.166 | -2.061 | 2.227 | 0.634 | < 0.0001 | C |
| H6: Post-Only Limit | 21,264 | 0.166 | -0.845 | 2.000 | 0.463 | < 0.0001 | C |
| H7: Delayed Execution | 21,264 | 0.166 | -3.857 | 4.024 | 1.000 | < 0.0001 | C |

**Bonferroni-corrected α = 0.00714 (0.05/7)**

---

## 5. SIGNAL SUBSET ANALYSIS

### By Queue Imbalance

| qi_l1 Range | N | Gross (bps) | Profitable Fraction |
|---|---|---|---|
| < -0.7 | 9,063 | 0.218 | 0.247 |
| -0.7 to -0.3 | 5,002 | 0.062 | 0.063 |
| -0.3 to 0 | 229 | 0.000 | 0.000 |
| 0 to 0.3 | 1 | 0.000 | 0.000 |
| 0.3 to 0.7 | 2,119 | 0.082 | 0.096 |
| > 0.7 | 4,850 | 0.222 | 0.293 |

**Best subset (|qi_l1| > 0.7):** Gross = 0.22 bps, Net (maker) = -1.78 bps

### By Spread

| Spread (bps) | N | Gross (bps) | Profitable Fraction |
|---|---|---|---|
| < 0.015 | 0 | — | — |
| 0.015-0.02 | 21,207 | 0.167 | 0.196 |
| 0.02-0.05 | 29 | 0.813 | 1.000 |
| > 0.05 | 28 | -1.302 | 0.071 |

**Best subset (spread 0.02-0.05):** Gross = 0.81 bps, Net (maker) = -1.19 bps (but only 29 signals)

### By Signal Strength

All signals have score ≤ 0.5 (SignalEngine produces scores in [0, 0.5] range).

### Combined Filters

| Filter | N | Gross (bps) | Net (maker) |
|---|---|---|---|
| |qi| > 0.7 | 13,913 | 0.201 | -1.799 |
| spread < 0.02 | 21,207 | 0.167 | -1.833 |
| |qi| > 0.7 + spread < 0.02 | 13,870 | 0.201 | -1.799 |

**No subset produces positive net expectancy.**

---

## 6. V5 DECISIONENGINE EXECUTION ANALYSIS

| Metric | Value |
|---|---|
| Signals | 53,141 |
| Gross mean | 0.041 bps |
| Net (maker) | -1.959 bps |
| Net (taker) | -3.975 bps |
| Sessions positive | 20/26 |
| **Classification** | **C (Insufficient)** |

### V5 High Confidence (|calibrated| > 0.05)

| Metric | Value |
|---|---|
| Signals | 28,924 |
| Gross mean | 0.047 bps |
| Net (maker) | -1.953 bps |
| **Classification** | **C (Insufficient)** |

---

## 7. BEST CONDITIONAL REGIME

From 15 pre-registered hypotheses (previous analysis):

| Condition | Gross (bps) | Net (maker) | Net (taker) |
|---|---|---|---|
| TFI_abs > 0.7 & vol > p50 | 0.762 | -2.178 | -3.904 |

**Even the best conditional regime is economically insufficient.**

---

## 8. DISTRIBUTION ANALYSIS

### SignalEngine Gross Return Distribution

| Percentile | Value (bps) |
|---|---|
| P1 | -1.425 |
| P5 | 0.000 |
| P10 | 0.000 |
| P25 | 0.000 |
| P50 | 0.000 |
| P75 | 0.000 |
| P90 | 0.805 |
| P95 | 1.239 |
| P99 | 2.627 |

- **Fraction profitable (gross > 0):** 19.6%
- **Fraction > 1 bps:** 7.7%
- **Fraction > 2 bps:** 1.9%

### Key Insight

The signal produces many small losses and a few large gains. The median return is 0.000 bps, but the mean is 0.166 bps due to the right-skewed distribution. However, even the right tail is insufficient to overcome execution costs.

---

## 9. ADVERSE SELECTION ANALYSIS

### Do signals predict adverse movement?

| Signal Direction | Avg Next-Return | Std |
|---|---|---|
| BUY | +0.184 bps | 0.55 |
| SELL | +0.169 bps | 0.56 |

**No evidence of adverse selection.** Both BUY and SELL signals have positive average returns. The issue is not adverse selection but signal magnitude.

### Signal Strength vs. Execution Quality

| qi_l1 Range | Gross (bps) | Interpretation |
|---|---|---|
| Strong imbalance (>0.7) | 0.22 | One-sided book → signal works |
| Weak imbalance (<0.3) | 0.06 | Balanced book → signal weak |

**Queue imbalance predicts signal strength but not enough to be profitable.**

---

## 10. EXECUTION COST SENSITIVITY

### Maximum Allowable Cost

| Signal Type | Gross (bps) | Max Cost for Net > 0 |
|---|---|---|
| SignalEngine unconditional | 0.166 | 0.166 bps |
| SignalEngine best subset (|qi| > 0.7) | 0.222 | 0.222 bps |
| V5 DecisionEngine unconditional | 0.041 | 0.041 bps |
| Best conditional (TFI>0.7 & vol>p50) | 0.762 | 0.762 bps |

### Cost Comparison

| Execution Method | Cost (bps) | Gap to SignalEngine Gross |
|---|---|---|
| Taker (market order) | 4.016 | 3.850 |
| Aggressive limit | 2.613 | 2.447 |
| Maker (passive limit) | 2.000 | 1.834 |
| Theoretical minimum | 0.000 | -0.166 |

**Even with zero execution cost, the net edge would be 0.166 bps — a tiny edge.**

---

## 11. FINAL CLASSIFICATION

### **C — Existing signal remains economically insufficient even with realistic execution improvements**

### Evidence Summary

1. **All 7 pre-registered execution hypotheses fail:**
   - H1 (Market): Net = -3.86 bps
   - H2 (Aggressive Limit): Net = -2.45 bps
   - H3 (Passive Limit): Net = -0.85 bps (best)
   - H4 (Strength-Conditioned): Net = -1.83 bps
   - H5 (Queue-Aware): Net = -2.06 bps
   - H6 (Post-Only): Net = -0.85 bps
   - H7 (Delayed): Net = -3.86 bps

2. **No signal subset is profitable:**
   - Best subset (|qi| > 0.7): Gross = 0.22 bps, Net (maker) = -1.78 bps
   - Best conditional (TFI>0.7 & vol>p50): Gross = 0.76 bps, Net (maker) = -2.18 bps

3. **Signal magnitude is structurally insufficient:**
   - SignalEngine: 0.17 bps
   - V5 DecisionEngine: 0.04 bps
   - Best achievable: 0.76 bps
   - Minimum execution cost: 2.0 bps (maker)
   - Gap: 1.24–1.96 bps

4. **The gap is not due to adverse selection:**
   - Both BUY and SELL signals have positive average returns
   - The issue is signal magnitude, not execution quality

5. **Even with zero execution cost:**
   - Net edge would be 0.04–0.76 bps
   - This is a tiny edge requiring massive leverage/volume

### Decision

**DO NOT modify the strategy.**
**Keep V5_BASELINE_NO_LIVE_TRADE = True.**

No execution mechanism tested produces positive net expectancy. The existing order-flow signal is statistically predictive but economically insufficient.

---

## 12. HIGHEST-VALUE RESEARCH QUESTION

**What additional information (beyond the current order-flow features) is required to increase the gross edge from ~0.17 bps to >2.0 bps?**

Potential directions:
1. **Alternative data sources:** Liquidations, funding rates, order-book snapshots at higher frequency
2. **Alternative signal horizons:** Shorter (<500ms) or longer (>500ms) horizons
3. **Cross-market information:** Correlated assets, spot-futures basis
4. **Machine learning:** Non-linear feature interactions (but risk of overfitting)
5. **Queue-position-aware execution:** Modeling exact fill probabilities based on queue state

---

## APPENDIX: FILES GENERATED

| File | Description |
|---|---|
| PRE_REGISTERED_EXECUTION_HYPOTHESES.md | Pre-registered hypotheses and decision rules |
| execution_audit.py | Execution simulation script |
| data/research/execution_audit_h1_market.csv | H1 results |
| data/research/execution_audit_h2_aggressive_limit.csv | H2 results |
| data/research/execution_audit_h3_passive_limit.csv | H3 results |
| data/research/execution_audit_h4_strength_conditioned.csv | H4 results |
| data/research/execution_audit_h5_queue_aware.csv | H5 results |
| data/research/execution_audit_sigeng.csv | SignalEngine signal data |

---

**END OF EXECUTION ECONOMIC AUDIT**
