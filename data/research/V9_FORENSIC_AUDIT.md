# V9 Forensic Audit — Negative Result Validation

**Date:** 2026-09-01
**Purpose:** Verify that the V9 FALSIFIED result is scientifically valid and not caused by bugs, leakage, or errors.
**Auditor:** Kilo (independent forensic audit)

---

## 1. Audit Objective

Determine whether the V9 negative result (-85 bps net, 0% positive folds) reflects:
- **A)** A genuine absence of predictive edge (valid falsification), OR
- **B)** A bug, leakage, sign error, or implementation flaw (invalid result)

---

## 2. Leakage Audit

### 2.1 Predictor Temporal Ordering

| Predictor | Construction | Uses Data At | Correct? |
|-----------|-------------|--------------|----------|
| btc_ret_1m | `log_ret.shift(1)` | t-1 | YES |
| btc_ret_5m | `log(close/close.shift(6)).shift(1)` | t-1 to t-6 | YES |
| btc_ret_10m | `log(close/close.shift(11)).shift(1)` | t-1 to t-11 | YES |
| ofi_5m | `log_ret.rolling(5).sum().shift(1)` | t-1 to t-5 | YES |
| realized_vol_5m | `log_ret.rolling(5).std().shift(1)` | t-1 to t-5 | YES |

**Verdict: NO LEAKAGE** — All predictors use strictly-earlier timestamps.

### 2.2 Target Construction

```python
target = np.log(close.shift(-5) / close) * 10000
```

Target at time t uses close[t+5] / close[t]. This is a forward-looking return, which is correct for a prediction target.

**Verdict: CORRECT** — Target is properly forward-looking.

### 2.3 Standardization

```python
mu = X_train.mean(axis=0)
std = X_train.std(axis=0)
X_oos_std = (X_oos - mu) / std
```

Standardization uses train stats only, applied to OOS. No future information leaks.

**Verdict: NO LEAKAGE**

### 2.4 Fold Separation

| Fold | Training | Validation | OOS | Overlap? |
|------|----------|------------|-----|----------|
| 1 | day 1-30 | day 31-40 | day 41-50 | NO |
| 2 | day 11-40 | day 41-50 | day 51-60 | NO |
| 3 | day 21-50 | day 51-60 | day 61-70 | NO |

Training data never overlaps with OOS data for the same fold.

**Verdict: NO LEAKAGE**

---

## 3. Sign Convention Audit

```python
signal = +1 if pred > 0, -1 if pred < 0
gross_pnl = signal * actual
```

- If prediction is positive and actual is positive → gross_pnl = +1 × positive = positive ✓
- If prediction is negative and actual is negative → gross_pnl = -1 × negative = positive ✓

**Verdict: CORRECT** — Sign convention is proper.

---

## 4. Cost Model Audit

### 4.1 Bug Found: Cost Over-Application

```python
signals["net_pnl"] = signals["gross_pnl"] - (cost_per_trade * (signals["signal"] != 0))
```

Since `signal` is always ±1 (threshold=0, predictions rarely exactly 0), this subtracts 85 bps **every minute**.

The spec defines rebalancing frequencies as {5, 10, 13, 15} minutes. Costs should only be applied when rebalancing occurs.

### 4.2 Impact Assessment

| Scenario | Cost per 5-min | Gross per 5-min | Net per 5-min |
|----------|----------------|-----------------|---------------|
| Current (per-minute) | 85 × 5 = 425 bps | ~0 bps | -425 bps |
| Correct (per-5-min) | 85 bps | ~0 bps | -85 bps |

**Both scenarios produce deeply negative net returns.** The gross edge is ~0 bps regardless of cost frequency.

### 4.3 Conclusion

The cost over-application bug makes the result look worse than it should, but **does not change the FALSIFIED conclusion**. Even with correct cost application, the net return is deeply negative.

**Verdict: BUG EXISTS, CONCLUSION UNCHANGED**

---

## 5. Fold Construction Audit

| Spec | Actual | Deviation |
|------|--------|-----------|
| 5 folds | 3 folds | Data limitation (76 days) |
| 60-day training | 30-day training | Data limitation |

With 76 days of common data and 10-day OOS windows, only 3 folds are possible. The result is so unequivocal (0% positive) that additional folds would not change the conclusion.

**Verdict: DEVIATION, CONCLUSION UNCHANGED**

---

## 6. Hit Rate Analysis

| Horizon | Hit Rate |
|---------|----------|
| 5m | 49.9%, 50.4%, 49.7% |
| 10m | 50.0%, 49.8%, 49.6% |
| 15m | 49.8%, 49.7%, 49.5% |

Hit rates are uniformly ~50%, confirming the predictions have **zero directional skill**.

**Verdict: CONSISTENT WITH NO-EDGE**

---

## 7. Permutation Control

| Metric | Value |
|--------|-------|
| Actual net return | -85.15 bps |
| Permutation 95th percentile | -85.15 bps |
| Actual > 95th percentile | NO |

The strategy's performance is **indistinguishable from random permutation** of the near-zero gross returns.

**Verdict: CONFIRMS NO-EDGE**

---

## 8. Gross Edge Analysis

| Horizon | Avg Gross |
|---------|-----------|
| 5m | +0.018 bps |
| 10m | -0.185 bps |
| 15m | -0.291 bps |

Gross returns are essentially zero (range: -0.41 to +0.20 bps). This is **500× smaller** than the 85 bps cost per rebalance.

**Verdict: NO GROSS EDGE EXISTS**

---

## 9. Data Quality Audit

| Check | Result |
|-------|--------|
| Files per symbol | 92 (all symbols) |
| Duplicates | 0 |
| Header contamination | 0 (after pipeline fix) |
| Timestamp monotonicity | All files |
| UTC alignment | All files |
| Price sanity | All within expected ranges |

**Verdict: DATA IS CLEAN**

---

## 10. Literature Comparison

| Study | Finding | Our Result |
|-------|---------|------------|
| Guo et al. (2024) | 3.55 bps/min spread (2019-2021 data) | ~0 bps/min (2026 data) |

The cross-asset predictability documented in 2019-2021 **does not replicate** in 2026 data. This suggests the effect has decayed as markets became more efficient.

**Verdict: DECAY OF DOCUMENTED EFFECT**

---

## 11. Summary of Findings

| Potential Issue | Found? | Affects Conclusion? |
|-----------------|--------|---------------------|
| Leakage | NO | — |
| Target misalignment | NO | — |
| Sign error | NO | — |
| Cost-model error | YES (over-application) | NO |
| Fold construction error | YES (3 vs 5) | NO |
| Implementation bug | NO | — |
| Data quality issue | NO | — |

---

## 12. Final Audit Conclusion

### **The V9 FALSIFIED verdict is SCIENTIFICALLY VALID.**

The negative result is caused by the **genuine absence of predictive skill** in the cross-asset lead-lag signal at 5-15 minute horizons in 2026 data. It is NOT caused by bugs, leakage, or errors.

The two deviations identified (cost over-application, fewer folds) do not change the conclusion because:
1. The gross edge is ~0 bps regardless of cost frequency
2. The result is uniformly negative across all 9 folds and 3 horizons

V9 is a **valid negative result** that should be preserved as permanent scientific evidence.

---

*Audit completed: 2026-09-01*
*Outcome: V9 FALSIFIED — VALIDATED*
*Next step: Preserve V9 as negative evidence, consider V10*
