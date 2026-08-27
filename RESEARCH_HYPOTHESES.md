# RESEARCH HYPOTHESES — PHASE 3

**Date:** 2026-08-26
**Status:** Pre-registered before evaluation

---

## BOTTLENECK SUMMARY

The information bottleneck is **SIGNAL MAGNITUDE**:
- Current gross edge: 0.04–0.76 bps
- Execution costs: 2.0–4.7 bps
- Gap: 1.8–4.5 bps

The existing features (OFI, TFI, queue imbalance, depth imbalance) capture genuine but tiny predictive information. To close the gap, we need features with **larger economic magnitude**.

---

## PRE-REGISTERED HYPOTHESES

### Hypothesis A: Order Flow Toxicity (Volume-Synchronized Probability of Informed Trading)

**Research Basis:**
- Easley, Lopez de Prado, O'Hara (2012) "Flow Toxicity and Liquidity in a High-Frequency World"
- VPIN (Volume-synchronized Probability of Informed Trading) predicts short-term reversals
- High toxicity → informed trading → price impact → reversal

**Mechanism:**
Order flow toxicity measures the probability that trades are informed. When toxicity is high, the short-term price impact is likely to reverse as the informed order flow is absorbed.

**Feature Construction:**
```
VPIN-like = |buy_volume - sell_volume| / total_volume over volume buckets
Use existing tfi_500 as proxy, but compute over VOLUME buckets (not time buckets)
```

**Pre-Registered Parameters:**
- Volume bucket size: 1% of average session volume (approximately 50-100 trades)
- Lookback: 50 volume buckets
- Threshold: VPIN > 0.7 (top decile)

**Expected Direction:**
High toxicity → predict short-term reversal (opposite of current TFI signal)

**Falsification Test:**
If VPIN has no predictive power (gross ≈ 0), the hypothesis is falsified.

**Preregistered Alpha:** 0.05/3 = 0.0167 (Bonferroni correction for 3 hypotheses)

---

### Hypothesis B: Multi-Level Book Imbalance Interaction

**Research Basis:**
- Cont, Kukanov, Stoikov (2014) "Price Impact of Order Book Events"
- Multi-level imbalance has non-linear predictive power
- Interaction between levels captures depth resilience

**Mechanism:**
Single-level imbalance (qi_l1) is transient. The interaction between L1 and L5 imbalance captures whether the book is consistently one-sided (strong signal) or just at the touch (weak signal). A consistent one-sided book across levels indicates genuine directional pressure.

**Feature Construction:**
```
imbalance_interaction = qi_l1 * di_l5
Positive when L1 and L5 agree (both bid-heavy or both ask-heavy)
Negative when they disagree
```

**Pre-Registered Parameters:**
- Use existing qi_l1 and di_l5 (no new parameters)
- Interaction: simple product
- Threshold: |imbalance_interaction| > 0.3 (top quartile)

**Expected Direction:**
Consistent multi-level imbalance → stronger directional signal

**Falsification Test:**
If the interaction term has no incremental predictive power over qi_l1 alone, the hypothesis is falsified.

---

### Hypothesis C: Trade Size-Weighted Flow Imbalance

**Research Basis:**
- Chordia, Subrahmanyam, Roll (2002) "Order Imbalance, Liquidity, and Market Returns"
- Large trades have more information content than small trades
- Size-weighted flow predicts short-term returns better than aggregate flow

**Mechanism:**
Current TFI treats all trades equally. But large trades are more likely to be informed. Weighting trade flow by size should increase signal-to-noise ratio.

**Feature Construction:**
```
size_weighted_tfi = sum(trade_size * direction) / sum(trade_size)
where direction = +1 for buyer-initiated, -1 for seller-initiated
Use 500ms window (same as tfi_500)
```

**Pre-Registered Parameters:**
- Window: 500ms (same as existing tfi_500)
- Weighting: linear in trade size
- No threshold (continuous feature)

**Expected Direction:**
Large trades in signal direction → stronger predictive power

**Falsification Test:**
If size-weighted TFI has lower correlation with future returns than aggregate TFI, the hypothesis is falsified.

---

## HYPOTHESIS REGISTRATION TABLE

| ID | Name | Research Basis | Feature | Alpha |
|---|---|---|---|---|
| A | Order Flow Toxicity | Easley et al. (2012) | VPIN-like volume buckets | 0.0167 |
| B | Multi-Level Imbalance | Cont et al. (2014) | qi_l1 * di_l5 | 0.0167 |
| C | Size-Weighted Flow | Chordia et al. (2002) | Size-weighted TFI | 0.0167 |

**Total hypotheses:** 3
**Bonferroni-corrected α:** 0.0167
**Evaluation period:** Chronological OOS (sessions 212451-232919)

---

## ECONOMIC ACCEPTANCE GATE (PRE-REGISTERED)

A hypothesis passes only if ALL of the following are true:

1. Gross edge > 0 AND p < 0.0167 (Bonferroni-corrected)
2. Net edge (maker) > 0 AFTER realistic execution costs
3. Session stability: > 60% of sessions have positive gross
4. Not concentrated in a single session or regime
5. Confidence interval lower bound > 0

If no hypothesis passes all conditions, the algorithm is classified as ECONOMICALLY INSUFFICIENT.

---

## WHAT CONSTITUTES FAILURE

A hypothesis FAILS if:
- Gross edge is not statistically significant (p > 0.0167)
- Net edge (maker) is negative
- Results are concentrated in < 4 sessions
- The effect disappears in permutation control

---

## NO PARAMETER FISHING

The following are PROHIBITED:
- Adjusting thresholds after seeing results
- Testing multiple parameter combinations
- Selecting the best-looking specification
- Adding features beyond the 3 pre-registered hypotheses
- Changing the OOS evaluation period

If all 3 hypotheses fail, we STOP and report ECONOMICALLY INSUFFICIENT.
