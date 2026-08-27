# Forensic Replication Audit — Corrected
## Binance Order Flow AutoTrader v2 — Strict Category Classification

**Audit Date:** 2026-08-21  
**Trigger:** Terminology inconsistency in previous forensic replication report  
**Scope:** Strict classification of work performed into three explicit categories  
**Constraints:** No strategy modification, no parameter tuning, no V5 baseline changes, no live trading, no governance bypass  

---

## Executive Summary

| Dimension | Result |
|-----------|--------|
| **Final Classification** | **A. VERIFIED RECALCULATION + ECONOMICALLY NEGATIVE (TRUE INDEPENDENT REPLICATION OUTSTANDING)** |
| **Replication Status** | **REPLICATION_FAIL / OUTSTANDING** (true independent replication NOT performed) |
| **Economic Verdict** | **NO_EDGE** (verified by independent recalculation) |
| **Live Trading** | **HARD-BLOCKED** (V5_BASELINE_NO_LIVE_TRADE = True) |
| **Software Tests** | 167/167 PASS |

**Key Correction:** The previous report incorrectly labeled "independent recalculation/verification" (Category 2) as "independent replication" (Category 3). This report fixes that terminology error.

---

## 1. Three Explicit Categories

### Category 1: Original Calculation
| Aspect | Detail |
|--------|--------|
| **Definition** | Original economic reports produced by project's own validation pipeline |
| **Files** | `v5_verdict.json`, `V6_COMPREHENSIVE_VALIDATION.json`, `v5_q2_report.json` |
| **Code Used** | `app/v5_economic_report.py`, `app/v6_comprehensive_validation.py`, `app/v5_cost.py`, `app/v5_validation.py` |
| **Data Used** | `v5_features.parquet`, `v6_features.parquet` |
| **Independently Implemented** | ❌ No (original code) |
| **Same Source Code Reused** | ✅ Yes (original) |
| **Same Intermediate Predictions Reused** | ✅ Yes |
| **Sample Size** | 3,889 |
| **Formulas** | Gross: `mean(sign(pred)*r_500)`; Gated: `mean(sign(pred)*y - gate) for |pred|>gate` |
| **Results** | V5 gross: 0.06408 bps, gated: 0.0; V6 gross: 0.0719 bps, gated: 0.0 |

### Category 2: Independent Recalculation / Verification (What Was Actually Done)
| Aspect | Detail |
|--------|--------|
| **Definition** | Independent re-execution of the SAME source code on the SAME data to verify computational correctness. Same code, same data, same environment. **Not independent replication.** |
| **What Was Done** | Step-by-step re-execution of the EXACT same pipeline (`v5_economic_report.py`, `v6_comprehensive_validation.py`) on the SAME data using the SAME source code in the SAME environment, step-by-step, to verify computational correctness. |
| **Dataset Used** | SAME `v5_features.parquet`, `v6_features.parquet` |
| **Code Used** | SAME source code (`app/v5_economic_report.py`, `app/v6_comprehensive_validation.py`, `app/v5_model.py`, `app/v6_model.py`, `app/v5_cost.py`) |
| **Independently Implemented** | ❌ No (reused original code) |
| **Same Source Code Reused** | ✅ Yes |
| **Same Intermediate Predictions Reused** | ❌ No (predictions regenerated) |
| **Predictions Regenerated** | ✅ Yes (independently computed from models) |
| **Sample Size** | 3,889 (exactly matched) |
| **Exact Formulas Replicated** | Gross: `mean(sign(pred)*r_500)`; Gated: `mean(sign(pred)*y - gate) for |pred|>gate` |
| **Results Matched** | ✅ All calculations match exactly |
| **Classification** | **Category 2: Independent Recalculation/Verification** |
| **Note** | This is a VERIFICATION of computational correctness, NOT an independent replication. Same code, same data, same environment. |

### Category 3: True Independent Replication (Outstanding — Required by Protocol)
| Aspect | Detail |
|--------|--------|
| **Definition** | Completely independent reconstruction from source raw data using independently implemented code, independent feature engineering, independently trained models, independent cost model, on NEW untouched data. |
| **Protocol Requirements** | 1. Collect NEW untouched Binance USDⓈ-M Futures data<br>2. Apply identical V6 feature engineering (independently implemented)<br>3. Use same frozen V6 model (no refitting)<br>4. Apply same cost model (Q2 contemporary) - independently implemented<br>5. Run identical Signal Decision Engine gates (independently implemented)<br>6. Report gross expectancy, net expectancy, HAC p-values<br>7. Compare with original OOS results |
| **Acceptance Criteria** | Net expectancy > 0 bps; Gross HAC p < 0.05; Net HAC p < 0.05; Regime robust; Long/short symmetric |
| **What Was Done** | **NOTHING** — No new data collected, no independent feature engineering, no independent model training, no independent cost model, no independent Signal Decision Engine |
| **Dataset Used** | SAME existing OOS data |
| **Code Used** | SAME original source code |
| **Independently Implemented** | ❌ No |
| **New Data Collected** | ❌ No |
| **Independent Feature Engineering** | ❌ No |
| **Independent Model Training** | ❌ No |
| **Independent Cost Model** | ❌ No |
| **Independent Decision Engine** | ❌ No |
| **Status** | **NOT PERFORMED — OUTSTANDING (Required by protocol before deployment review)** |
| **Protocol File** | `data/research/v6/report_11_replication_protocol.json` |

---

## 3. Category Comparison Summary

| Aspect | Category 1: Original Calculation | Category 2: Independent Recalculation/Verification | Category 3: True Independent Replication |
|--------|----------------------------------|---------------------------------------------------|------------------------------------------|
| **Performed** | ✅ Yes | ✅ Yes (this audit) | ❌ **NOT PERFORMED** |
| **Data** | Original OOS | Same original OOS | NEW untouched data (required) |
| **Code** | Original pipeline | Same original pipeline | Independently implemented |
| **Predictions** | Original | Regenerated from models | Independently generated |
| **Cost Model** | Original | Same original | Independently implemented |
| **Decision Engine** | Original | Same original | Independently implemented |
| **Status** | Completed (original) | Completed (this audit) | **OUTSTANDING** (required by protocol) |
| **What This Audit Did** | N/A | Category 2: Verification | **NOT PERFORMED** |

---

## 4. Corrected Classification

| Original (Incorrect) | Corrected |
|----------------------|-----------|
| "Final Classification: B. REPRODUCED + ECONOMICALLY NEGATIVE" | **A. VERIFIED RECALCULATION + ECONOMICALLY NEGATIVE (TRUE INDEPENDENT REPLICATION OUTSTANDING)** |
| "NO_EDGE / REPLICATION_FAIL was fully reproduced and confirmed by independent calculation" | "NO_EDGE verified by independent recalculation; true independent replication OUTSTANDING" |
| "Independent Replication = NOT PERFORMED" + "REPRODUCED + ECONOMICALLY NEGATIVE" | **Category 2 completed; Category 3 OUTSTANDING** |

**Terminology Correction:** "REPRODUCED" in original report referred to computational verification (Category 2), NOT true independent replication (Category 3). The term "REPLICATION_FAIL" correctly reflects that Category 3 was not performed.

---

## 4. V6 Incremental R² Investigation (Independent)

### Exact Calculation Reproduced
| Metric | Value |
|--------|-------|
| V5 R² | 0.102707 |
| V6 R² | -0.573328 |
| Incremental R² | **-0.676035** |
| V5-V6 Correlation | 0.552484 |
| V6 Residual Correlation with y | 0.127100 |
| V6 Residual t-stat | 7.9817 |
| V6 Residual p-value | 0.000000 |

### Interpretation (Independent Analysis)

| Aspect | Finding |
|--------|---------|
| **V5 R²** | 0.1027 — V5 explains ~10% of r_500 variance (positive, reasonable) |
| **V6 R²** | **-0.573** — NEGATIVE because V6 predictions are in ARBITRARY UNITS (max ~3.5) vs r_500 in bps (max ~1.4). V6 predictions on completely different scale → MSE huge → R² negative |
| **Incremental R²** | **-0.676** — V6 performs WORSE than V5 alone due to scale mismatch |
| **V6 Residual Correlation with y** | **0.1271 (p=0.000)** — **Statistically significant**! V6 residuals DO contain incremental predictive information about r_500 |
| **V6 Residual t-stat** | 7.9817 (p=0.000) — Highly significant |

**Critical Interpretation:**
- **Negative incremental R² (-0.676) does NOT mean V6 has no incremental information**
- V6 IS miscalibrated (predictions in arbitrary units, not bps), destroying overall R²
- **V6 residual correlation with y IS statistically significant (p=0.000, t=7.98)** → V6 DOES contain incremental predictive information about r_500
- The problem is **CALIBRATION** (scale mismatch), not lack of information
- V6 contains incremental predictive information but is miscalibrated → destroys net R²

**Conclusion:** V6 DOES contain incremental predictive information (residual correlation p=0.000), but the model is miscalibrated (predictions in arbitrary units, not bps). The negative incremental R² reflects calibration failure, not lack of information.

---

## Corrected Final Classification

| Dimension | Result |
|-----------|--------|
| **Category 1: Original Calculation** | ✅ Completed (original reports) |
| **Category 2: Independent Recalculation/Verification** | ✅ **COMPLETED** (all calculations match exactly) |
| **Category 3: True Independent Replication** | ❌ **OUTSTANDING** (required by protocol) |
| **Economic Verdict** | **NO_EDGE** (verified by independent recalculation) |
| **Replication Status** | **OUTSTANDING** (Category 3 not performed) |
| **Economic Verdict** | **NO_EDGE** (verified by independent recalculation) |
| **Live Trading** | **HARD-BLOCKED** (V5_BASELINE_NO_LIVE_TRADE = True) |

---

## Corrected Final Classification

**A. VERIFIED RECALCULATION + ECONOMICALLY NEGATIVE (TRUE INDEPENDENT REPLICATION OUTSTANDING)**

**Reasons:**
1. All calculations independently recalculated (Category 2) — all match exactly
2. Zero trades executed in OOS (0/3,889 rows) at actual gate threshold
3. Net expectancy zero or negative after realistic costs at ALL gate levels
4. Net expectancy not statistically distinguishable from zero (HAC p=1.0)
5. Cost-to-gross ratio 48-73× exceeds breakeven by 48-73×
6. Break-even cost (0.064-0.072 bps) exceeded by 48-73×
7. Zero directional trades executed (0 LONG, 0 SHORT) at actual gate
8. V6 adds zero incremental economic value (incremental R² negative due to calibration)
9. **TRUE INDEPENDENT REPLICATION NOT PERFORMED (Category 3 outstanding)**
10. Multiple testing correction fails for net expectancy
11. No regime shows positive net expectancy
12. Governance lock `V5_BASELINE_NO_LIVE_TRADE = True` remains active

---

## Final Verdict

**A. VERIFIED RECALCULATION + ECONOMICALLY NEGATIVE (TRUE INDEPENDENT REPLICATION OUTSTANDING)**

- **Economic Verdict:** NO_EDGE (verified by independent recalculation)
- **True Independent Replication:** OUTSTANDING (Category 3 not performed — required by protocol)
- **Live Trading:** HARD-BLOCKED by `V5_BASELINE_NO_LIVE_TRADE = True`
- **Software:** 167/167 tests PASS

**The NO_EDGE economic finding is verified by independent recalculation (Category 2). True independent replication (Category 3) remains OUTSTANDING per protocol.**

---

## Final Determination

| Dimension | Result |
|-----------|--------|
| **Software** | 167/167 tests PASS — Production-hardened for paper trading |
| **Economic** | **NO_EDGE** (verified by independent recalculation) |
| **Replication** | **OUTSTANDING** (Category 3 not performed — required by protocol) |
| **Live Trading** | **HARD-BLOCKED** (V5_BASELINE_NO_LIVE_TRADE = True) |

**No strategy changes. No parameter tuning. No governance bypass. No live trading enabled.**