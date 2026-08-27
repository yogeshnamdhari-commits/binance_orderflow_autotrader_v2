# FORENSIC VALIDATION PHASE 2 — TIER A: LONG-HORIZON RE-VALIDATION

**Date:** 2026-08-19  
**Project:** `/Users/targetmobile/Downloads/binance_orderflow_autotrader_v2`  
**Status:** READ-ONLY AUDIT — NO STRATEGY CHANGES  
**Baseline:** `ORDERFLOW_BASELINE_V5` — frozen, NO LIVE TRADING  
**Artifact:** `data/research/FORENSIC_VALIDATION_PHASE_2_TIER_A.json`

---

## 1. PURPOSE AND GOVERNANCE

Tier A answers one scientific question only:

> Does the **existing frozen 500 ms signal direction** (from `v3_model.json`) contain predictive information that persists at longer holding horizons?

This is a **zero-refit** evaluation. The following constraints are strictly observed:
- `v3_model.json` is **not modified**.
- No new model coefficients are generated.
- No feature set is changed.
- No parameters are optimized.
- No production code is touched.
- No live or paper trading is initiated.

The test uses the **existing genuine held-out OOS split** (3,889 rows) and pre-registered horizons `2 000, 5 000, 10 000, 30 000 ms`.

---

## 2. DATA AND METHOD

### 2.1 OOS Window
| Property | Value |
|----------|-------|
| Start (UTC) | 2026-08-19 01:20:20.885 |
| End (UTC) | 2026-08-19 01:25:21.993 |
| Span | 301,108 ms (~5.0 min) |
| Rows | 3,889 |
| Median event gap | 102.0 ms |

### 2.2 Signal Definition
```
gross_return_h = sign(pred_500ms) * r_h
pred_500ms     = frozen ridge OLS prediction from v3_model.json at horizon 500 ms
r_h            = (mid_{first event >= t+h} - mid_t) / mid_t * 1e4
```

### 2.3 Cost Gate
- **4.6658 bps** taker round-trip.
- Derived from `data/hist/research/execution_calibration.json`.
- **HISTORICAL AND NON-CONTEMPORANEOUS.** Sampler collected ~42 hours **before** the OOS window (`2026-08-17 18:16 UTC` vs OOS `2026-08-19 01:20 UTC`).
- Used here as an **indicative reference only**. It does **not** establish contemporaneous execution profitability.

### 2.4 Statistical Inference
Classical standard errors assume independence, which is violated at longer horizons because returns overlap. Primary inference uses **HAC Newey-West standard errors** with Bartlett kernel and max lag = `min(5 × median_gap, N−1)` = 510.

> **Effective sample note:** N is the raw observation count. Because multi-horizon returns overlap, the effective statistical information is smaller than N. HAC SE is the primary inferential statistic.

---

## 3. RESULTS

### 3.1 Primary Tier-A Table

| Horizon (ms) | N | Gross (bps) | Historical Cost (bps) | Net (bps) | 95% CI (HAC) | HAC p-value | Verdict |
|-------------|---:|------------:|----------------------:|----------:|--------------|------------|---------|
| 2 000 | 3,864 | +0.0801 | 4.6658 | **−4.5857** | [ +0.0161 , +0.1441 ] | 0.0142 | STOP |
| 5 000 | 3,779 | +0.0685 | 4.6658 | **−4.5973** | [ −0.0051 , +0.1422 ] | 0.0683 | STOP |
| 10 000 | 3,725 | +0.0725 | 4.6658 | **−4.5933** | [ −0.0408 , +0.1857 ] | 0.2098 | STOP |
| 30 000 | 3,499 | +0.0757 | 4.6658 | **−4.5901** | [ −0.3272 , +0.4785 ] | 0.7127 | STOP |

### 3.2 Breakdown by Direction (5000 ms representative)

| Direction | n | Gross (bps) | Net Taker (bps) |
|-----------|---|------------:|----------------:|
| LONG | 2,837 | +0.0064 | −4.6594 |
| SHORT | 942 | +0.2557 | −4.4101 |

*Pattern is consistent across all horizons: SHORT gross > LONG gross, but both are far below cost.*

### 3.3 Regime Breakdown (5000 ms representative)

| Regime | n | Gross (bps) | Net Taker (bps) |
|--------|---|------------:|----------------:|
| `normal` | 2,426 | +0.1218 | −4.5440 |
| `high_impact` | 1,353 | −0.0270 | −4.6928 |

The `normal` regime produces slightly positive gross at longer horizons; `high_impact` remains negative.

### 3.4 HAC vs Classical SE

| Horizon | Classical SE (bps) | HAC SE (bps) | Ratio |
|---------|-------------------:|-------------:|------:|
| 2 000 | 0.0070 | 0.0327 | 4.7× |
| 5 000 | 0.0084 | 0.0376 | 4.5× |
| 10 000 | 0.0105 | 0.0578 | 5.5× |
| 30 000 | 0.0184 | 0.2055 | 11.2× |

Classical SE severely underestimates uncertainty at longer horizons due to overlapping returns. HAC SE inflates correctly; at 30 000 ms the HAC SE is 11× classical.

---

## 4. SCIENTIFIC CONCLUSION

### 4.1 Does the frozen 500 ms signal have directional persistence at longer horizons?

**Weak, marginally significant at the shortest longer horizon only.**

- At **2 000 ms**, gross expectancy is +0.0801 bps (HAC p = 0.014). The 95% HAC CI excludes zero narrowly: [ +0.0161 , +0.1441 ]. This is the **only** horizon where gross is statistically distinguishable from zero under HAC inference.
- At **5 000 ms**, gross falls to +0.0685 bps (HAC p = 0.068). The HAC CI includes zero: [ −0.0051 , +0.1422 ].
- At **10 000 ms** and **30 000 ms**, gross is +0.0725 and +0.0757 bps respectively, but HAC CIs widen dramatically and include zero with high p-values (0.21 and 0.71).

The directional persistence, if any, is **tiny** and disappears under dependence-robust inference beyond 2 seconds.

### 4.2 Does the result survive the historical 4.6658 bps cost gate?

**No.** At every horizon, net expectancy is deeply negative:

- Net taker at 2 000 ms: **−4.5857 bps** (STOP verdict).
- Net taker at 5 000 ms: **−4.5973 bps** (STOP verdict).
- Net taker at 10 000 ms: **−4.5933 bps** (STOP verdict).
- Net taker at 30 000 ms: **−4.5901 bps** (STOP verdict).

The gap between gross signal and cost is **≈ 58–67×** the gross magnitude. The signal does not approach break-even at any tested horizon.

### 4.3 Is the evidence statistically significant?

**Gross:** marginally significant at 2 000 ms only (HAC p = 0.014). Not significant at any longer horizon.  
**Net:** not significant at any horizon because net = gross − 4.6658, and the constant shift means the sign is trivially determined. The relevant question is economic magnitude, not significance of a known-negative number.

### 4.4 Does the existing frozen algorithm have a deployable economic edge at any tested horizon?

**No.** The ORDERFLOW_BASELINE_V5 frozen 500 ms signal contains, at best, minuscule directional information that:

1. Does **not** persist robustly beyond 2 seconds under dependence-robust inference.
2. Is **57–67× smaller** than the historical execution cost gate at all tested horizons.
3. Cannot clear the economic gate in any subgroup (LONG, SHORT, `normal` regime, or `high_impact` regime).

**Final verdict: NO STATISTICALLY SIGNIFICANT DEPLOYABLE EDGE.**

---

## 5. LIMITATIONS

1. **Temporal mismatch:** Cost gate is 42 hours stale. A contemporaneous cost sample may be higher or lower, but would need to be **< 0.08 bps** for the signal to become profitable — which is implausible for Binance BTCUSDT taker execution.
2. **Overlapping returns:** HAC corrects SE inflation but does not restore lost effective sample size. The 30 000 ms result has very low effective information despite 3,499 raw observations.
3. **Short OOS window:** ~5 minutes across 2 sessions. Results are consistent with Phase 2 (250/500/1 000 ms) but span a limited market regime.
4. **V2 projections are not V3/V5 validation:** The 2 000 / 5 000 ms V2 train-slice projections remain distinct from this Tier-A test of the current frozen signal.

---

## 6. NEXT STEPS

**Stop.** Do not proceed to Tier B (refitting) or data collection.

The scientifically justified path is:
1. If the project goal is a deployable Binance order-flow strategy, the existing signal formulation has failed economic validation at all tested horizons.
2. The next investigation — if authorized — is a **strategic re-evaluation** of whether the order-flow information structure has economically meaningful memory at horizons longer than 30 seconds, requiring genuinely new data and a contemporaneous execution-cost sample.
3. Q2 (contemporaneous execution cost) remains a **separate** future data-collection stage.

**Current status remains: ORDERFLOW_BASELINE_V5 — NO LIVE TRADING.**

---

*Report generated: 2026-08-19*  
*Auditor: Kilo (read-only audit)*  
*Tier: A — zero-refit longer-horizon validation*
