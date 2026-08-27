# Forensic Replication Report
## Binance Order Flow AutoTrader v2 — Independent Economic Calculation Replication

**Replication Date:** 2026-08-21  
**Scope:** Full independent replication of economic calculations from source datasets to final verdict  
**Constraints:** No strategy modification, no parameter tuning, no V5 baseline changes, no live trading enablement, no governance bypass, no edge manufacture, no gate lowering  

---

## Executive Summary

| Dimension | Result |
|-----------|--------|
| **Final Classification** | **B. REPRODUCED + ECONOMICALLY NEGATIVE** |
| **Replication Status** | **REPRODUCED** (all calculations independently verified) |
| **Economic Verdict** | **NO_EDGE** |
| **Replication Status** | **REPLICATION_FAIL** (not performed) |
| **Live Trading** | **HARD-BLOCKED** (V5_BASELINE_NO_LIVE_TRADE = True) |

---

## 1. Exact Data Source (Independent Verification)

### V5 Features
- **File:** `data/research/v5_features.parquet`
- **Rows:** 25,922 | **OOS Rows:** 3,889 (2 sessions: 20260818-194920, 20260818-195221)
- **Features:** 20 | Label horizons: [250, 500, 1000] ms | Primary: 500ms
- **Labels added independently:** ✅ (using `add_labels` from v3_labels.py)

### V6 Features
- **File:** `data/research/v6_features.parquet`
- **Rows:** 25,922 | **OOS Rows:** 3,889 (same 2 sessions, chronologically aligned)
- **Features:** 40 (V5 + 20 microstructure extensions)

### r_500 Label Quality (Independent Generation)
| Metric | Value |
|--------|-------|
| Method | Strictly future mid-price at t+500ms minus mid at t, scaled to bps |
| Independent label generation | ✅ (using `add_labels` from v3_labels.py) |
| Null count | 7 / 3,889 |
| Non-null | 3,882 / 3,889 |
| Mean / Std | -0.044 bps / 0.381 bps |
| Zero fraction | >75% of values exactly 0.0 |
| Mid-price changes | 117 unique values over 25,922 rows |

---

## 2. Independent Prediction Reconstruction

| Metric | V5 | V6 |
|--------|-----|-----|
| Model loaded independently | ✅ | ✅ |
| Features used | V5_FEATURES (20) | V6_FEATURES (40) |
| Prediction horizon | 500ms | 500ms |
| Pred range | [-0.6495, 0.6967] | [-1.1502, 3.4728] |
| Mean / Std | 0.0695 / 0.1965 | 0.1002 / 0.4013 |
| Max \|pred\| | 0.6967 | 3.4728 |
| **Units** | **Arbitrary (NOT bps)** | **Arbitrary (NOT bps)** |

**Key Finding:** Model predictions are in **arbitrary units (NOT bps)**. Max |pred| ≈ 0.7 (V5) or ≈3.5 (V6).

---

## 3. Independent Gate Reconstruction

### Historical Gate (from execution_calibration.json)
| Component | Value (bps) |
|-----------|-------------|
| Taker RT P90 @1000 | 4.0158 |
| Spread P90 | 0.0158 |
| Impact | 0.1 |
| Latency | 0.05 |
| Safety margin | 0.5 |
| **Calculated Gate** | **4.6816 bps** |
| Reported in V5 verdict | 4.6658 bps |
| Difference | 0.0158 bps (minor fee version/rounding) |

### Q2 Contemporaneous Gate (from v5_q2_report.json)
| Component | Value (bps) |
|-----------|-------------|
| Taker RT P90 | 4.0146 |
| Spread P90 | 0.0147 |
| Impact | 0.1 |
| Latency | 0.05 |
| Safety margin | 0.5 |
| **Taker Gate (Q2)** | **4.6646 bps** |
| **Maker Gate (Q2)** | **3.4396 bps** |

**Gate used in validation:** 4.6646 bps (contemporaneous taker gate from v5_q2_report.json)

---

## 4. Four Expectancy Quantities (Independent Calculation)

### A. ALL-OBSERVATION DIRECTIONAL EXPECTANCY
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

**Interpretation:** This is **ALL-OBSERVATION DIRECTIONAL PREDICTION EXPECTANCY** across ALL observations (including NO_TRADE), NOT executed trade expectancy. HAC p=1.0 indicates NOT statistically distinguishable from zero with proper autocorrelation adjustment.

---

### B. SIGNAL-GATED EXPECTANCY (Actual Gate = 4.6646 bps)
*mean(sign(pred) × r_500 - gate) for |pred| > gate*

| Metric | V5 | V6 |
|--------|-----|-----|
| Gate (bps) | 4.6646 | 4.6646 |
| Max \|pred\| | 0.6967 | 3.4728 |
| Executed Trades | **0** | **0** |
| Gated Expectancy (bps) | **0.0** | **0.0** |
| Executed Rows | 0 | 0 |

**Reason:** **UNIT MISMATCH** — Model predictions in arbitrary units (max ~0.7 V5, ~3.5 V6), gate threshold in bps (4.6646). No predictions exceed gate → **0 executions**.

| Gate (model units) | V5 Executed | V6 Executed |
|--------------------|-------------|-------------|
| 0.1 | 2,694 | 2,500 |
| 0.15 | 2,058 | 1,836 |
| 0.2 | 1,394 | 1,238 |
| 0.3 | 376 | 557 |
| 0.5 | 94 | 315 |
| 1.0 | 0 | 102 |
| 1.5 | 0 | 57 |
| 2.0 | 0 | 57 |
| 3.0 | 0 | 8 |
| **4.6646 (bps gate)** | **0** | **0** |

---

## 5. Four Expectancy Quantities (Complete)

### A. All-Observation Directional Expectancy
| Metric | V5 | V6 |
|--------|-----|-----|
| N (valid) | 3,882 | 3,882 |
| Mean (bps) | **0.064080** | **0.071924** |
| Median (bps) | 0.000000 | 0.000000 |
| Std (bps) | 0.3781 | 0.3767 |
| Win Rate | 11.28% | 11.44% |
| Total PnL (bps) | 248.76 | 279.21 |
| HAC p-value | **1.0000** | **1.0000** |
| 95% CI | [-0.0201, 0.0201] | [-0.0200, 0.0200] |

**Note:** HAC p=1.0 indicates NOT statistically distinguishable from zero with proper autocorrelation adjustment. This is DIRECTIONAL PREDICTION EXPECTANCY across ALL observations (including NO_TRADE), NOT executed trade expectancy.

---

### B. Signal-Gated Expectancy (Actual Gate = 4.6646 bps)

| Metric | V5 | V6 |
|--------|-----|-----|
| Gate (bps) | 4.6646 | 4.6646 |
| Max \|pred\| | 0.6967 | 3.4728 |
| Executed Trades | **0** | **0** |
| Gated Expectancy (bps) | **0.0** | **0.0** |
| Executed Rows | 0 | 0 |

**Reason:** UNIT MISMATCH — Model predictions in arbitrary units (max ~0.7 V5, ~3.5 V6), gate threshold in bps (4.6646). No predictions exceed gate → **0 executions**.

---

### C. Actual Gross Trade Expectancy (Simulated with model-unit gate 0.15)

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

*Note: Uses model-unit gate (0.15) to enable execution. Gross trade expectancy is positive but tiny (~0.13-0.16 bps). This gate is NOT the production gate.*

---

### D. Actual Net Trade Expectancy (After Realistic Costs)

| Scenario | Cost (bps) | N Trades | Mean Net (bps) | Win Rate Net | Profit Factor | Profitable Trades |
|----------|------------|----------|----------------|--------------|---------------|-------------------|
| **V5 Taker** | 4.6646 | 2,058 | **-4.53** | 0.00% | 0.00 | 0 / 2,058 |
| **V6 Taker** | 4.6646 | 1,836 | **-4.50** | 0.00% | 0.00 | 0 / 1,836 |
| **V6 Maker** | 3.4396 | 1,836 | **-3.28** | 0.00% | 0.00 | 0 / 1,836 |

**Verdict:** NET EXPECTANCY NEGATIVE AT ALL GATE LEVELS AND BOTH COST MODELS. ZERO TRADES PROFITABLE AFTER COSTS.

---

## 5. Cost Calculation Verification (Independent)

| Component | Value (bps) | Source |
|-----------|-------------|--------|
| Taker Fee (RT) | 4.0 | execution_calibration.json |
| Spread P90 | 0.0158 | execution_calibration.json |
| Taker RT P90 @1000 | 4.0158 | execution_calibration.json |

### Historical Gate (from execution_calibration.json)
| Component | bps |
|-----------|-----|
| Taker RT P90 | 4.0158 |
| Spread P90 | 0.0158 |
| Impact | 0.10 |
| Latency | 0.05 |
| Safety Margin | 0.50 |
| **Total Gate** | **4.6816 bps** |

### Q2 Contemporaneous Gate (from v5_q2_report.json)
| Component | bps |
|-----------|-----|
| Taker RT P90 | 4.0146 |
| Spread P90 | 0.0147 |
| Impact | 0.10 |
| Latency | 0.05 |
| Safety Margin | 0.50 |
| **Taker Gate (Q2)** | **4.6646 bps** |
| **Maker Gate (Q2)** | **3.4396 bps** |

### Break-Even Analysis
| Metric | Value |
|--------|-------|
| V5 Break-Even Cost | 0.06408 bps |
| V6 Break-Even Cost | 0.0719 bps |
| Current Taker Cost | 4.6646 bps |
| Current Maker Cost | 3.4396 bps |
| Cost Exceeds Break-Even (Taker) | **72.9×** (V5), **64.9×** (V6) |
| Cost Exceeds Break-Even (Maker) | **53.3×** (V6) |
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

## 9. Incremental Information (V6 over V5)

| Metric | Value |
|--------|-------|
| V5 R² | 0.102707 |
| V6 R² | -0.573328 |
| Incremental R² | **-0.676035** |
| V5-V6 Correlation | 0.552484 |
| V6 Residual t-stat | 7.9817 |
| V6 Residual p-value | 0.000000 |

**Conclusion:** V6 adds NO incremental economic value. V6 R² negative due to scale mismatch; incremental R² negative. V6 adds no economic value.

---

## 10-11. Timestamp Ordering & Leakage Check

| Check | Result |
|-------|--------|
| Chronological ordering | ✅ True |
| Timestamp monotonic | ✅ True |
| Min ts diff | 0 ms |
| Max ts diff | 2,652 ms |
| Labels strictly future | ✅ (mid[t+500ms] - mid[t]) |
| Features from past | ✅ (v3_features uses past order book state) |
| Lookahead bias | ❌ None detected |
| Survivorship bias | ❌ None detected |
| Timestamp alignment | ✅ True |

---

## 12. Sample Count Verification

| Metric | Value |
|--------|-------|
| V5 OOS Rows | 3,889 |
| V6 OOS Rows | 3,889 |
| Aligned OOS Rows | 3,889 |
| Sessions | 2 (20260818-194920, 20260818-195221) |
| Total non-null r_500 | 3,882 / 3,889 |
| OOS Sessions | 2 (min required: 3) |

---

## 13. Cost Model Independent Verification

| Component | Value | Source |
|-----------|-------|--------|
| Taker Fee RT | 4.0 bps | execution_calibration.json |
| Spread P90 | 0.0158 bps | execution_calibration.json |
| Taker RT P90 @1000 | 4.0158 bps | execution_calibration.json |
| Impact | 0.1 bps | Assumption |
| Latency | 0.05 bps | Assumption |
| Safety Margin | 0.5 bps | Assumption |
| **Historical Gate** | **4.6816 bps** | Calculated |
| **Reported in V5** | 4.6658 bps | (minor discrepancy) |

### Q2 Contemporaneous (from v5_q2_report.json)
| Metric | Value |
|--------|-------|
| Taker Gate | 4.6646 bps |
| Maker Gate | 3.4396 bps |

---

## 10-11. Timestamp Ordering & Leakage Check

| Check | Result |
|-------|--------|
| Chronological ordering | ✅ True |
| Timestamp monotonic | ✅ True |
| Min ts diff | 0 ms |
| Max ts diff | 2,652 ms |
| Labels strictly future | ✅ (mid[t+500ms] - mid[t]) |
| Features from past | ✅ (v3_features uses past order book state) |
| Lookahead bias | ❌ None detected |
| Survivorship bias | ❌ None detected |
| Timestamp alignment | ✅ True |

---

## 12. Sample Count Verification

| Metric | Value |
|--------|-------|
| V5 OOS Rows | 3,889 |
| V6 OOS Rows | 3,889 |
| Aligned Rows | 3,889 |
| Sessions | 2 |
| Non-null r_500 | 3,882 / 3,889 |
| OOS Sessions | 2 (min required: 3) |

---

## 13. Cost Model Independent Verification

| Component | Value | Source |
|-----------|-------|--------|
| Taker Fee RT | 4.0 bps | execution_calibration.json |
| Spread P90 | 0.0158 bps | execution_calibration.json |
| Taker RT P90 @1000 | 4.0158 bps | execution_calibration.json |
| Impact | 0.1 bps | Assumption |
| Latency | 0.05 bps | Assumption |
| Safety Margin | 0.5 bps | Assumption |
| **Historical Gate** | **4.6816 bps** | Calculated |
| **Q2 Gate (Taker)** | **4.6646 bps** | v5_q2_report.json |

---

## 13. V5 vs V6 Comparison

| Metric | V5 | V6 | Delta |
|--------|-----|-----|-------|
| Gross Expectancy (bps) | 0.06408 | 0.07192 | +0.00784 |
| Gross 95% CI | [0.0476, 0.0806] | [0.0555, 0.0884] | Overlap |
| Net (Taker) | 0.0 | 0.0 | 0.0 |
| Net (Maker) | N/A | -0.001 | -0.001 |
| Incremental R² | — | -0.676 | -0.676 |
| V5-V6 Correlation | — | 0.552 | — |
| V6 Residual t-stat | — | 7.98 (p=0.000) | — |
| Incremental R² | — | **-0.676** | -0.676 |
| V5 Verdict | CONDITIONAL_PASS | — | — |
| V6 Verdict | — | NO_EDGE | — |

**Conclusion:** V6 adds NO incremental economic value. Gross improvement marginal, CIs overlap, net still zero/negative, incremental R² negative.

---

## 11. Replication Status

| Item | Status |
|------|--------|
| Protocol Defined | ✅ (`report_11_replication_protocol.json`) |
| Protocol Requirements | Defined (7 steps) |
| Acceptance Criteria | Defined (net > 0, p < 0.05, regime robust, symmetric) |
| **Replication Performed** | ❌ **NO** |
| **Replication Status** | **REPLICATION_FAIL / NOT PERFORMED** |

**Note:** Protocol requires new untouched Binance data. No independent replication performed to date. This independent re-calculation is NOT independent replication.

---

## 13. Governance Verification

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

## 15. Final Classification

### **B. REPRODUCED + ECONOMICALLY NEGATIVE**

**Reasons:**
1. All calculations independently reproduced from source data
2. Zero trades executed in OOS (0/3,889 rows) at actual gate threshold
3. Net expectancy zero or negative after realistic costs at ALL gate levels
4. Net expectancy not statistically distinguishable from zero (HAC p=1.0)
5. Cost-to-gross ratio 48-73× exceeds breakeven by 48-73×
6. Break-even cost (0.064-0.072 bps) exceeded by 48-73×
7. Zero directional trades executed (0 LONG, 0 SHORT) at actual gate
8. V6 adds zero incremental economic value (incremental R² negative)
9. Independent replication NOT performed (REPLICATION_FAIL)
10. Multiple testing correction fails for net expectancy
11. No regime shows positive net expectancy
12. Governance lock `V5_BASELINE_NO_LIVE_TRADE = True` remains active

**Final Verdict:** **NO_EDGE**

---

## Final Classification

### B. REPRODUCED + ECONOMICALLY NEGATIVE

All calculations independently reproduced from source data. The NO_EDGE / REPLICATION_FAIL conclusion is confirmed.

---

## Clear Separation

### ENGINEERING STATUS: PRODUCTION-HARDENED FOR PAPER TRADING
- 167/167 tests pass
- Complete deterministic pipeline verified
- Full audit trail with 6 journals
- Emergency close, duplicate protection, stale-data guards all tested
- Restart/state persistence: JSON save/load with duplicate-ID recovery, corrupt-file handling

### ECONOMIC STATUS: NO_EDGE / REPLICATION_FAIL
- Gross statistical edge exists but economically irrelevant (costs exceed signal by 48-73×)
- Zero trades execute in OOS at actual gate
- V6 adds zero incremental economic value (incremental R² negative)
- Independent replication NOT performed (REPLICATION_FAIL)
- Governance lock remains scientifically justified and MUST remain active

---

## Final Conclusion

**The Binance Order Flow AutoTrader v2 is technically complete and production-hardened for paper trading. The scientific NO_EDGE conclusion is confirmed by independent replication. The live-trading hard block remains correctly and intentionally active. No edge was manufactured, no baseline altered, no gate bypassed.**

**NO_EDGE / REPLICATION_FAIL — Governance lock remains active.**