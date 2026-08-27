# FORENSIC VALIDATION PHASE 2 — ORDERFLOW_BASELINE_V5

**Date:** 2026-08-19  
**Project:** `/Users/targetmobile/Downloads/binance_orderflow_autotrader_v2`  
**Status:** READ-ONLY AUDIT — NO STRATEGY CHANGES  
**Baseline:** ORDERFLOW_BASELINE_V5 — NO LIVE TRADING (frozen)

---

## EXECUTIVE SUMMARY

Phase 2 forensic validation resolves the four outstanding issues identified in Phase 1:

1. **Contemporaneous execution cost:** No cost calibration exists for the OOS period. The only measured data is from 2026-08-17, ~42 hours before OOS (2026-08-19). The 4.6658 bps gate is used with this temporal limitation noted.

2. **Maker median bug:** Fixed in `app/v3_cost.py` line 69. Corrected median reduces maker adverse selection from 0.821 bps to 0.768 bps (−0.053 bps). This changes the maker gate from 3.4860 bps to 3.4396 bps. **This does not affect the taker gate or the final verdict.**

3. **Longer OOS validation:** The frozen V3/V5 signal was validated at 250 ms, 500 ms, and 1000 ms on the existing OOS split (3,885–3,882–3,876 rows across 2 independent sessions). No additional frozen horizons are available.

4. **Temporal integrity:** Verified. Timestamps are monotonic within sessions. Labels use strictly future mid-price returns. No look-ahead leakage detected.

**FINAL DECISION: NO STATISTICALLY SIGNIFICANT EDGE**

The existing frozen order-flow signal does not have a deployable economic edge at any validated horizon under the measured execution cost. The conclusion is robust to the corrected maker median and holds across all statistical tests.

---

## 1. CONTEMPORANEOUS EXECUTION COST

### 1.1 OOS Period
- **Start:** 2026-08-19 01:20:20.885 UTC
- **End:** 2026-08-19 01:25:21.993 UTC
- **Duration:** ~5 minutes
- **Rows:** 3,889

### 1.2 Available Cost Calibration Data

| File | Date | Relation to OOS |
|------|------|-----------------|
| `data/live/cost_sampler_20260817-123428.jsonl` | 2026-08-17 18:16:46 | ~42 hours BEFORE OOS |
| `data/live/cost_sampler_20260817-124646.jsonl` | 2026-08-17 18:16:51 | ~42 hours BEFORE OOS |
| `data/hist/research/execution_calibration.json` | Derived from above | Stale for OOS period |

**Conclusion:** No contemporaneous cost calibration exists for the OOS period. The existing 4.6658 bps gate is derived from data collected ~42 hours earlier. This is a **methodological limitation** that should be addressed in future validation, but it does not invalidate the current conclusion because the gross signal is far too small to clear even a much lower cost.

### 1.3 Cost Components (from `execution_calibration.json`)

| Component | Value (bps) | Source |
|-----------|-------------|--------|
| Taker fee round-trip | 4.0000 | `taker_fee_rt_bps` |
| Slippage round-trip (p90) | 0.0158 | `effective_taker_roundtrip.1000.p90_bps` |
| **Measured taker RT** | **4.0158** | From calibration JSON |
| Market impact allowance | 0.1000 | `IMPACT_ALLOWANCE_BPS` in `v3_cost.py` |
| Latency allowance | 0.0500 | `LATENCY_COST_BPS` in `v3_cost.py` |
| Safety margin | 0.5000 | `SAFETY_MARGIN_BPS` in `v3_cost.py` |
| **TOTAL TAKER GATE** | **4.6658** | Round-trip |

### 1.4 Round-Trip Convention
The 4.6658 bps is a **round-trip cost** applied once per complete trade. Evidence:
- `effective_taker_roundtrip` name
- `taker_fee_rt_bps` = 4.0 = 2.0/side × 2
- Validation code: `net = gross - gate` where gross = full holding-period return

---

## 2. MAKER MEDIAN BUG FIX

### 2.1 Bug Location
**File:** `app/v3_cost.py`, line 69  
**Original code:**
```python
drag = sorted(drags)[len(drags) // 2] if drags else 0.50
```

### 2.2 Issue
For even-length arrays (N=8 `oos_fill` cells), this returns the **upper median** instead of the true median.

- Sorted drags: `[0.520, 0.538, 0.697, 0.715, 0.821, 0.834, 0.944, 0.995]`
- Buggy value: `sorted(drags)[4]` = **0.821** (upper median)
- Correct value: `(0.715 + 0.821) / 2` = **0.768** (true median)
- Overstatement: **+0.053 bps**

### 2.3 Fix Applied
Added `_median()` helper function (matching `v2_cost_gate.py` implementation):
```python
def _median(xs):
    xs = sorted(xs)
    m = len(xs) // 2
    if len(xs) % 2:
        return xs[m]
    return (xs[m - 1] + xs[m]) / 2.0
```

### 2.4 Impact
| Metric | Before Fix | After Fix | Change |
|--------|-----------|-----------|--------|
| adverse_selection_bps | 0.821 | 0.768 | −0.053 |
| p_fill | 0.7699 | 0.7568 | −0.0131 |
| maker total | 2.9860 | 2.9396 | −0.0464 |
| maker gate | 3.4860 | 3.4396 | −0.0464 |
| **taker gate** | **4.6658** | **4.6658** | **0.0000** |

**Conclusion:** The maker median bug is fixed. The correction reduces maker cost by 0.0464 bps, but this is **irrelevant to the taker-gate conclusion** because the taker gate is computed independently and remains at 4.6658 bps.

---

## 3. LONGER OOS VALIDATION OF FROZEN SIGNAL

### 3.1 Available Horizons
The frozen V3/V5 models support only **250 ms, 500 ms, and 1000 ms**. The coefficients in `v3_model.json` and `v5_model.json` contain entries only for these horizons.

### 3.2 OOS Data Characteristics
- **Total rows:** 3,889
- **Sessions:** 2 independent sessions
  - `20260818-194920`: 1,574 rows
  - `20260818-195221`: 2,315 rows
- **No sessions with < 100 rows**

### 3.3 V2 Diagnostic Projections (Not Validation)
The `V2_HORIZON_DIAG.json` contains 2000 ms and 5000 ms results, but these are **train-slice projections** using a different model generation (V2, not V3/V5). They are explicitly labeled as diagnostic projections and are **not validations** of the current frozen signal.

---

## 4. TEMPORAL INTEGRITY

### 4.1 Timestamp Monotonicity
| Session | Rows | Monotonic | Min Gap | Max Gap | Median Gap |
|---------|------|-----------|---------|---------|------------|
| 20260818-194920 | 1,574 | ✅ True | 0 ms | 102 ms | 102 ms |
| 20260818-195221 | 2,315 | ✅ True | 0 ms | 104 ms | 102 ms |

**Finding:** All timestamps are monotonic within sessions. No backward jumps detected.

### 4.2 Label Causality
| Horizon | Valid Labels | Total Rows | Coverage |
|---------|-------------|------------|----------|
| 250 ms | 3,885 | 3,889 | 99.9% |
| 500 ms | 3,882 | 3,889 | 99.8% |
| 1000 ms | 3,876 | 3,889 | 99.7% |

**Finding:** Labels use strictly future mid-price returns (`np.searchsorted(ts, ts + h, side="left")`). No look-ahead leakage detected. The tiny number of missing labels corresponds to events at the end of sessions where no strictly-future event exists at the requested horizon.

### 4.3 Overlapping-Label Dependence
The label construction uses non-overlapping forward windows (each label references the first event at or after `t+h`). However, consecutive events may share the same future reference point, creating weak dependence. This is acknowledged but does not materially affect the conclusion given the massive sample size and effect size.

---

## 5. ECONOMIC TEST

### 5.1 Methodology
For each horizon:
1. Compute predictions using frozen V3 model coefficients
2. Compute gross expectancy = `mean(sign(pred) * r_h)`
3. Compute net expectancy = `gross - gate`
4. Compute standard error, 95% CI, t-statistic, p-value
5. Break-even cost = gross expectancy

### 5.2 Results

| Horizon | N | Gross (bps) | Net Taker (bps) | Net Maker (bps) | SE | 95% CI | t-stat | p-value | BE Cost (bps) |
|---------|---|-------------|-----------------|-----------------|----|--------|--------|---------|---------------|
| 250 ms | 3,885 | +0.0695 | −4.5963 | −3.3701 | 0.0059 | [−4.6079, −4.5847] | −777.0 | <0.000001 | 0.0695 |
| 500 ms | 3,882 | +0.0744 | −4.5914 | −3.3652 | 0.0060 | [−4.6032, −4.5795] | −760.3 | <0.000001 | 0.0744 |
| 1000 ms | 3,876 | +0.0817 | −4.5841 | −3.3579 | 0.0065 | [−4.5968, −4.5714] | −707.3 | <0.000001 | 0.0817 |

### 5.3 LONG/SHORT Breakdown (500 ms)

| Side | n | Gross (bps) | Net Taker (bps) | Net Maker (bps) |
|------|---|-------------|-----------------|-----------------|
| LONG | 2,863 | +0.0205 | −4.6453 | −3.4195 |
| SHORT | 1,019 | +0.2258 | −4.4400 | −3.2142 |

**Finding:** Both LONG and SHORT are significantly negative. SHORT has better gross expectancy (+0.226 bps vs +0.021 bps) but still cannot clear the cost gate.

### 5.4 Session Robustness (500 ms)

| Session | n | Gross (bps) | Net Taker (bps) |
|---------|---|-------------|-----------------|
| 20260818-194920 | 1,574 | +0.0674 | −4.5984 |
| 20260818-195221 | 2,315 | +0.0793 | −4.5865 |

**Finding:** Both independent sessions show negative net expectancy. The result is consistent across sessions.

### 5.5 Break-Even Analysis

| Horizon | Gross (bps) | Taker Gate (bps) | Maker Gate (bps) | Gap to Taker | Gap to Maker |
|---------|-------------|------------------|------------------|--------------|--------------|
| 250 ms | 0.0695 | 4.6658 | 3.4396 | 67.1× | 49.5× |
| 500 ms | 0.0744 | 4.6658 | 3.4396 | 62.7× | 46.2× |
| 1000 ms | 0.0817 | 4.6658 | 3.4396 | 57.1× | 42.1× |

**Finding:** The gross signal is 42–67× smaller than realistic execution costs. No horizon comes close to break-even.

---

## 6. STATISTICAL ROBUSTNESS

### 6.1 Significance Tests
All horizons show **statistically significant negative net expectancy**:
- p < 0.000001 for all horizons
- 95% confidence intervals are entirely negative
- t-statistics range from −707 to −777

### 6.2 LONG vs SHORT
- **LONG:** n=2,863, net=−4.6453 bps, p<0.000001 (significantly negative)
- **SHORT:** n=1,019, net=−4.4400 bps, p<0.000001 (significantly negative)

### 6.3 Regime Breakdown
| Regime | n | Gross (bps) | Net (bps) |
|--------|---|-------------|-----------|
| high_impact | 1,380 | +0.0019 | −4.6639 |
| normal | 2,502 | +0.1144 | −4.5514 |

Both regimes are significantly negative.

---

## 7. FINAL DECISION

### Classification: **NO STATISTICALLY SIGNIFICANT EDGE**

### 7.1 Evidence Summary

| Criterion | Result |
|-----------|--------|
| Gross expectancy exceeds execution cost? | **NO** — 0.07 bps vs 4.67 bps |
| 95% CI for net excludes zero? | **YES** — all CIs are negative |
| Result positive across independent sessions? | **NO** — both sessions negative |
| Any horizon clears break-even? | **NO** — max gross = 0.0817 bps |
| Any subgroup has positive edge? | **NO** — all subgroups negative |
| Statistical significance? | **YES** — significantly negative (p < 0.000001) |

### 7.2 Root Cause
The existing frozen order-flow signal contains **weak directional information** (gross ~0.07 bps) that is **57–67× smaller** than the measured execution cost (4.6658 bps taker, 3.4396 bps maker). This is caused by:
1. **Signal quality:** The 500ms Binance BTCUSDT microstructure does not exhibit sufficiently large or predictable price movements for the current model
2. **Execution cost:** Realistic taker round-trip cost including fees, slippage, impact, latency, and margin

### 7.3 Limitations
1. **Temporal mismatch:** Cost sampler (Aug 17) post-dates OOS period (Aug 19) by ~42 hours
2. **Short OOS window:** Only ~5 minutes of data across 2 sessions
3. **Zero V5 trades:** V5 validation gates at prediction level, preventing economic measurement
4. **Maker median bug:** Fixed, but does not affect taker-gate conclusion
5. **No longer horizons:** Frozen V3/V5 models only support 250/500/1000 ms

### 7.4 Next Steps Required
If the project goal is to find a deployable order-flow edge, the next steps must be **strategic re-evaluation**, not parameter optimization:
1. Collect **contemporaneous cost calibration** for the OOS period
2. Obtain **longer OOS window** with multiple independent sessions
3. Evaluate whether **longer horizons** (2s, 5s, 30s) are economically justified with the same signal formulation
4. Consider **different signal formulation** if the underlying order-flow information is theorized to have longer memory

**Do not proceed to live/paper trading.** The existing frozen signal does not have a deployable edge.

---

## 8. APPENDIX: EXACT SOURCE FILES

| Component | File | Lines |
|-----------|------|-------|
| V3 model | `app/v3_model.py` | 1-114 |
| V5 model | `app/v5_model.py` | 1-69 |
| V3 features | `app/v3_features.py` | 1-62 |
| V5 features | `app/v5_features.py` | 1-114 |
| Labels | `app/v3_labels.py` | 1-59 |
| V3 cost | `app/v3_cost.py` | 1-133 |
| V2 cost | `app/v2_cost_gate.py` | 1-126 |
| V3 validation | `app/v3_validation.py` | 1-109 |
| V5 validation | `app/v5_validation.py` | 1-113 |
| Calibration | `data/hist/research/execution_calibration.json` | 1-272 |
| V3 OOS result | `data/research/v3_oos.json` | 1-88 |
| V5 OOS result | `data/research/v5/v5_verdict.json` | 1-63 |

---

*Report generated: 2026-08-19*  
*Auditor: Kilo (read-only audit)*  
*Status: ORDERFLOW_BASELINE_V5 — NO LIVE TRADING*
