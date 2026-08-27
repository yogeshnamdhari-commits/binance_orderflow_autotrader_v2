# Forensic Economic Data Audit Report
## Binance Order Flow AutoTrader v2

**Audit Date:** 2026-08-20  
**Audit Scope:** Trace complete chain from original research datasets to final economic verdict  
**Constraints:** No strategy modification, no parameter tuning, no V5 baseline changes, no live trading enablement, no governance bypass, no edge manufacture  

---

## Executive Summary

| Dimension | Result |
|-----------|--------|
| **Final Classification** | **NO_EDGE** |
| **Replication Status** | **REPLICATION_FAIL** (not performed) |
| **Live Trading** | **HARD-BLOCKED** (V5_BASELINE_NO_LIVE_TRADE = True) |
| **Software Tests** | 167/167 PASS |
| **Economic Verdict** | **NO_EDGE / REPLICATION_FAIL** (unchanged) |

---

## 1. Exact Data Source

### V5 Features
- **File:** `data/research/v5_features.parquet`
- **Rows:** 25,922 total | **3,889 OOS** (2 sessions: 20260818-194920, 20260818-195221)
- **Features:** 20 | Label horizons: [250, 500, 1000] ms | Primary: 500ms
- **Splits:** Train 70% / Validation 15% / OOS 15% (chronological)

### V6 Features
- **File:** `data/research/v6_features.parquet`
- **Rows:** 25,922 | **3,889 OOS** (same 2 sessions, chronologically aligned)
- **Features:** 40 (V5 + 20 microstructure extensions)

### r_500 Label Quality
| Metric | Value |
|--------|-------|
| Method | Strictly future mid-price at t+500ms minus mid at t, scaled to bps |
| Null count | 7 / 25,922 |
| Non-null | 3,882 / 3,889 OOS |
| Mean / Std | -0.044 bps / 0.381 bps |
| Min / Max | -1.70 / 1.42 bps |
| Zero fraction | >75% of values exactly 0.0 |
| Mid-price changes | 117 unique values over 25,922 rows |

---

## 2. Exact Sample Size

| Metric | Value |
|--------|-------|
| V5 OOS Rows | 3,889 |
| V6 OOS Rows | 3,889 |
| OOS Sessions | 2 (20260818-194920: 1,574 rows; 20260818-195221: 2,315 rows) |
| **Executed Trades (V5)** | **0** |
| **Executed Trades (V6)** | **0** |
| LONG Trades | 0 |
| SHORT Trades | 0 |
| OOS Periods | 2 (min required: 3) |
| Min Signals/Direction Required | 200 |
| Actual Signals/Direction | 0 |

**Verdict:** **SEVERELY INADEQUATE** — Zero executed trades, zero directional signals, only 2 OOS periods.

---

## 3. Exact Computation Path

### Gross Expectancy Calculation
- **Method:** `mean(sign(prediction) * r_500)` across ALL OOS observations (3,889 rows)
- **Formula:** `gross_expectancy_bps = mean(sign(prediction) * r_500)`
- **V5 Result:** 0.06407983716249906 bps
- **V6 Result:** 0.07192436463353025 bps
- **N Observations:** 3,889 (both)
- **Note:** This is **DIRECTIONAL PREDICTION EXPECTANCY** across ALL observations (including NO_TRADE), NOT executed trade expectancy. The gate threshold is NOT applied.

### Gated Expectancy Calculation
- **Method:** `mean(sign(prediction) * r_500 - gate)` for `|prediction| > gate`
- **Gate Used:** 4.6658 bps (from `execution_calibration.json`)
- **Gate Units:** bps (from cost calibration)
- **Model Prediction Units:** Arbitrary units (NOT bps)
- **V5 Pred Range:** [-0.6495, 0.6967] | **V6 Pred Range:** [-1.1502, 3.4728]
- **Gate (bps):** 4.6658
- **V5 Executed Rows:** 0 | **V6 Executed Rows:** 0
- **V5 Gated Expectancy:** 0.0 | **V6 Gated Expectancy:** 0.0

**UNIT MISMATCH CONFIRMED:** Model predictions in arbitrary units (max ~0.7 V5, ~3.5 V6), gate threshold in bps (4.6658). No predictions exceed gate → **0 executions**.

---

## 4. Four Expectancy Quantities

### A. All-Observation Directional Expectancy
*mean(sign(prediction) × r_500) across ALL 3,889 OOS observations*

| Metric | V5 | V6 |
|--------|-----|-----|
| N (valid) | 3,882 | 3,882 |
| Mean (bps) | **0.064080** | **0.071924** |
| Median (bps) | 0.000000 | 0.000000 |
| Std (bps) | 0.3781 | 0.3767 |
| Win Rate | 11.28% | 11.44% |
| Total PnL (bps) | 248.76 | 279.21 |
| HAC SE | 0.01027 | 0.01023 |
| HAC z | 0.00 | 0.00 |
| HAC p-value | 1.0000 | 1.0000 |
| 95% CI | [-0.0201, 0.0201] | [-0.0200, 0.0200] |

**Interpretation:** This is **DIRECTIONAL PREDICTION EXPECTANCY** across ALL observations (including NO_TRADE), NOT executed trade expectancy. HAC p=1.0 indicates NOT statistically distinguishable from zero with proper autocorrelation adjustment.

---

### B. Signal-Gated Expectancy (Actual Gate = 4.6658 bps)
*mean(sign(pred) × r_500 - gate) for \|pred\| > gate*

| Metric | V5 | V6 |
|--------|-----|-----|
| Gate (bps) | 4.6658 | 4.6658 |
| Max \|pred\| | 0.6967 | 3.4728 |
| Executed Trades | **0** | **0** |
| Gated Expectancy (bps) | **0.0** | **0.0** |
| Executed Rows | 0 | 0 |

**Reason:** **UNIT MISMATCH** — Model predictions in arbitrary units (max ~0.7 V5, ~3.5 V6), gate threshold in bps (4.6658). No predictions exceed gate → **0 executions**.

---

### C. Actual Gross Trade Expectancy
*Simulated trades using realistic model-unit gate (0.15) to enable execution*

| Metric | V5 | V6 |
|--------|-----|-----|
| Gate (model units) | 0.15 | 0.15 |
| N Trades | 2,058 | 1,836 |
| LONG / SHORT | 1,572 / 486 | 1,413 / 423 |
| Mean Gross (bps) | 0.1328 | 0.1596 |
| Median (bps) | 0.0000 | 0.0000 |
| Std (bps) | 0.4312 | 0.4999 |
| Win Rate | 15.31% | 21.41% |
| Payoff Ratio | 1.627 | 1.295 |
| Profit Factor | 9.49 | 5.09 |
| Total Gross (bps) | 273.39 | 293.07 |

**Note:** Uses model-unit gate (0.15) to enable execution. Gross trade expectancy is positive but tiny (~0.13-0.16 bps). This gate is NOT the production gate.

---

### D. Actual Net Trade Expectancy (After Realistic Costs)

| Scenario | Cost (bps) | N Trades | Mean Net (bps) | Win Rate Net | Profit Factor | Profitable Trades |
|----------|------------|----------|----------------|--------------|---------------|-------------------|
| **V5 Taker** | 4.6646 | 2,058 | **-4.53** | 0.00% | 0.00 | 0 / 2,058 |
| **V6 Taker** | 4.6646 | 1,836 | **-4.50** | 0.00% | 0.00 | 0 / 1,836 |
| **V6 Maker** | 3.4396 | 1,836 | **-3.28** | 0.00% | 0.00 | 0 / 1,836 |

**Verdict:** **NET EXPECTANCY NEGATIVE AT ALL GATE LEVELS AND BOTH COST MODELS. ZERO TRADES PROFITABLE AFTER COSTS.**

---

## 5. Cost Calculation Verification

| Component | Value (bps) | Source |
|-----------|-------------|--------|
| Taker Fee (RT) | 4.0 | execution_calibration.json |
| Maker Fee (RT) | 2.0 | execution_calibration.json |
| Spread P90 | 0.0158 | execution_calibration.json |
| Taker RT P90 @1000 | 4.0158 | execution_calibration.json |

### Historical Gate (V5)
| Component | bps |
|-----------|-----|
| Taker RT P90 | 4.0158 |
| Spread P90 | 0.0158 |
| Impact | 0.10 |
| Latency | 0.05 |
| Safety Margin | 0.50 |
| **Total Gate** | **4.6658** |

### Q2 Contemporaneous (V6)
| Component | bps |
|-----------|-----|
| Taker RT P90 | 4.0146 |
| Spread P90 | 0.0147 |
| Impact | 0.10 |
| Latency | 0.05 |
| Safety Margin | 0.50 |
| **Taker Gate** | **4.6646** |
| **Maker Gate** | **3.4396** |

### Break-Even Analysis
| Metric | Value |
|--------|-------|
| V5 Break-Even Cost | 0.06408 bps |
| V6 Break-Even Cost | 0.0719 bps |
| Current Taker Cost | 4.6646 bps |
| Current Maker Cost | 3.4396 bps |
| Cost Exceeds Break-Even (Taker) | **72.9×** |
| Cost Exceeds Break-Even (Maker) | **53.3×** |
| Cost-to-Gross Ratio (V5 Taker) | **72.9×** |
| Cost-to-Gross Ratio (V6 Taker) | **64.9×** |
| Cost-to-Gross Ratio (V6 Maker) | **47.8×** |

---

## 6. Statistical Validity Check

| Test | V5 Gross | V6 Gross | V5 Net (Taker) | V6 Net (Taker) | V6 Net (Maker) |
|------|----------|----------|----------------|----------------|----------------|
| HAC z | 7.61 | 8.57 | 0.00 | 0.00 | 0.00 |
| HAC p | 0.0000 | 0.0000 | 1.0000 | 1.0000 | 1.0000 |
| Significant (α=0.05) | **YES** | **YES** | NO | NO | NO |

**Multiple Testing (Bonferroni, 108 experiments, α=0.000463):**
- Gross expectancy: **Passes** (p=0.0 < 0.000463)
- Net expectancy: **FAILS** (p=1.0 > 0.000463)

**Conclusion:** Gross directional edge is statistically significant but net expectancy is NOT distinguishable from zero (HAC p=1.0) because zero trades execute at actual gate.

---

## 7. Replication Status

| Item | Status |
|------|--------|
| Protocol Defined | ✅ (`report_11_replication_protocol.json`) |
| Protocol Requirements | Defined (7 steps) |
| Acceptance Criteria | Defined (net > 0, p < 0.05, regime robust, symmetric) |
| **Replication Performed** | ❌ **NO** |
| **Replication Status** | **REPLICATION_FAIL / NOT PERFORMED** |

**Note:** Protocol requires new untouched Binance data. No independent replication performed to date.

---

## 8. Data Quality Issues

| Issue | Severity | Details |
|-------|----------|---------|
| r_500 zero fraction | High | >75% of labels exactly 0.0 |
| Mid-price changes | Low | Only 117 changes over 25,922 observations |
| Label resolution | Medium | 75%+ of r_500 labels exactly 0.0 |
| Mid unique values | Low | 117 unique values over 25,922 rows |
| Label resolution | Medium | Mid changes only 117 times over 25,922 rows |

---

## 10. V5 vs V6 Comparison

| Metric | V5 | V6 | Delta |
|--------|-----|-----|-------|
| Gross Expectancy (bps) | 0.06408 | 0.07192 | +0.00784 |
| Gross 95% CI | [0.0476, 0.0806] | [0.0555, 0.0884] | Overlap |
| Net (Taker) | 0.0 | 0.0 | 0.0 |
| Net (Maker) | N/A | -0.001 | -0.001 |
| Incremental R² | — | 0.000 | 0.000 |
| V5-V6 Correlation | — | 0.552 | — |
| V6 Residual t-stat | — | 7.98 (p=0.000) | — |
| Incremental R² | — | 0.000 | 0.000 |

**V6 adds NO incremental economic value.** Gross improvement marginal, CIs overlap, net still zero/negative, incremental R² = 0.0.

---

## 11. Governance Verification

| Guard | Status | Location |
|-------|--------|----------|
| `V5_BASELINE_NO_LIVE_TRADE = True` | ✅ **IMMUTABLE** | `app/config.py` (hardcoded) |
| `LiveExecution.submit()` | ✅ **BLOCKED** | Raises `RuntimeError` |
| `TradeOrchestrator._governance_ok()` | ✅ **BLOCKED** | Returns `{blocked: true}` |
| `Config.assert_safe()` | ✅ **ENFORCED** | Raises in live mode |
| `Config.runtime_safe()` | ✅ **ENFORCED** | Returns `False` for live |
| `LIVE_TRADING_ENABLED` env | ✅ **FALSE** | Defaults to `false` in `.env` |

**Live trading CANNOT be enabled without modifying source code (governance constant is hardcoded).**

---

## 12. Final Classification

### **NO_EDGE**

**Reasons:**
1. Zero trades executed in OOS (0/3,889 rows) at actual gate threshold
2. Net expectancy zero or negative after realistic costs at ALL gate levels
3. Net expectancy not statistically distinguishable from zero (HAC p=1.0)
4. Cost-to-gross ratio 48-73× exceeds breakeven by 48-73×
5. Break-even cost (0.064-0.072 bps) exceeded by 48-73×
6. Zero directional trades executed (0 LONG, 0 SHORT) at actual gate
7. V6 adds zero incremental R² over V5 (incremental R² = 0.0)
8. Independent replication NOT performed (REPLICATION_FAIL)
9. Multiple testing correction fails for net expectancy (Bonferroni)
10. No regime shows positive net expectancy
11. Governance lock `V5_BASELINE_NO_LIVE_TRADE = True` remains active

---

## Final Determination

| Dimension | Result |
|-----------|--------|
| **Software Status** | **PRODUCTION-HARDENED FOR PAPER TRADING** (167/167 tests pass) |
| **Economic Status** | **NO_EDGE / REPLICATION_FAIL** |
| **Live Trading** | **HARD-BLOCKED** (governance lock active) |
| **Paper Trading** | Technically ready, economically pointless |

---

## Conclusion

The EXISTING order-flow signal strategy has **no deployable economic edge** after realistic transaction costs. The gross statistical edge (0.064-0.072 bps) is real but **economically irrelevant** — transaction costs exceed the gross signal by 48-73×. Zero trades execute in OOS at the actual gate threshold. The V6 extension adds zero incremental economic value. Independent replication has not been performed. The V5 governance lock (`V5_BASELINE_NO_LIVE_TRADE = True`) remains scientifically justified and MUST remain active.

**NO_EDGE / REPLICATION_FAIL — Governance lock remains active.**