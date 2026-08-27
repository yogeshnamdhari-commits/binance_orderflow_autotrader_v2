# Forensic Tier-A Economic Expectancy Analysis
## Binance Order Flow AutoTrader v2

**Analysis Date:** 2026-08-20  
**Status:** Final — No parameter search, no threshold tuning, no dataset modification  
**Governance:** V5_BASELINE_NO_LIVE_TRADE = True (hard-locked)  

---

## Executive Summary

**FINAL CLASSIFICATION: NO_EDGE**

The existing order-flow signal strategy shows a statistically significant gross expectancy (HAC p = 0.000), but **zero trades execute** after realistic transaction costs. Net expectancy is zero or negative after realistic costs. Cost-to-gross ratios of 48–73× exceed break-even by 48–73×. Independent replication has NOT been performed (REPLICATION_FAIL). The V5 governance lock (NO_EDGE) remains scientifically justified and MUST remain active.

---

## 1. Trade Count & Sample-Size Adequacy

| Metric | Value |
|--------|-------|
| OOS Total Rows | 3,889 |
| Executed Trades (V5) | 0 |
| Executed Trades (V6) | 0 |
| LONG Trades | 0 |
| SHORT Trades | 0 |
| OOS Sessions | 2 (1,574 + 2,315 rows) |
| Min Signals/Direction Required | 200 |
| Actual Signals/Direction | 0 |
| Min OOS Periods Required | 3 |
| Actual OOS Periods | 2 |

**Verdict:** **SAMPLE SIZE INADEQUATE** — Zero trades executed, zero directional signals, only 2 OOS periods.

---

## 2. Gross PnL Distribution Per Trade

**No trades executed.** No PnL distribution available.

---

## 3. Gross Expectancy (bps)

| Metric | V5 | V6 |
|--------|-----|-----|
| Gross Expectancy (bps) | 0.06408 | 0.07192 |
| Gross Std (bps) | 0.3781 | 0.3767 |
| HAC SE (bps) | 0.008425 | 0.008393 |
| HAC 95% CI | [0.0476, 0.0806] | [0.0555, 0.0884] |
| HAC z-stat | 7.61 | 8.57 |
| HAC p-value | 0.0000 | 0.0000 |
| Statistically Significant? | **YES** | **YES** |

**Gross edge is statistically significant but economically negligible.**

---

## 4. Measured Taker Cost (bps)

| Component | Value (bps) |
|-----------|-------------|
| Historical Gate (V5) | 4.6658 |
| Contemporaneous Gate | 4.6646 |
| Contemporaneous Taker Total | 4.1646 |
| — Taker RT P90 | 4.0146 |
| — Spread P90 | 0.0147 |
| — Impact | 0.10 |
| — Latency | 0.05 |
| — Safety Margin | 0.50 |
| Calibration Samples | 1,764 |

---

## 5. Net Expectancy After Costs (bps)

| Scenario | Net Expectancy (bps) | Executed N | Statistically Significant? |
|----------|---------------------|------------|---------------------------|
| V5 Taker (Historical) | 0.0 | 0 | No (p=1.0) |
| V6 Taker (Historical) | 0.0 | 0 | No (p=1.0) |
| V6 Taker (Contemporary) | 0.0 | 0 | No (p=1.0) |
| V6 Maker (Contemporary) | **-0.0010** | 1 | No (p=1.0) |

**Net expectancy is ZERO or NEGATIVE after realistic costs. Not statistically distinguishable from zero (HAC p = 1.0).**

---

## 6. Break-Even Round-Trip Cost

| Metric | Value (bps) |
|--------|-------------|
| V5 Break-Even Cost | 0.06408 |
| V6 Break-Even Cost | 0.0719 |
| Current Taker Cost | 4.6646 |
| Current Maker Cost | 3.4396 |
| Cost Exceeds Break-Even (Taker) | **72.9×** |
| Cost Exceeds Break-Even (Maker) | **53.3×** |

**Current costs exceed break-even by 53–73×.**

---

## 7. Cost Sensitivity Table

| Gate (bps) | V5 Net (bps) | V6 Net (bps) | Executed |
|------------|--------------|--------------|----------|
| 0.0 | +0.0641 | +0.0719 | — |
| 0.5 | -0.4359 | -0.4281 | — |
| 1.0 | -0.9359 | -0.9281 | — |
| 2.0 | -1.9359 | -1.9281 | — |
| 3.0 | -2.9359 | -2.9281 | — |
| 4.0 | -3.9359 | -3.9281 | — |
| **4.6658** | **0.0000** | **0.0000** | **0** |
| 5.0 | -4.9359 | -4.9281 | — |

*At current gate (4.6658 bps), net expectancy = 0. No trades execute.*

---

## 8. Win Rate, Loss Rate, Payoff Ratio, Profit Factor

| Metric | Value |
|--------|-------|
| Executed Trades | 0 |
| Wins | 0 |
| Losses | 0 |
| Win Rate | 0.0% |
| Loss Rate | 0.0% |
| Avg Win (bps) | N/A |
| Avg Loss (bps) | N/A |
| Payoff Ratio | N/A |
| Profit Factor | 0.0 |
| Sharpe | 0.0 |
| Max Drawdown (bps) | 0.0 |

**No trades executed — all metrics zero or N/A.**

---

## 9. Median Trade, Mean Trade, Tail Contribution

**No trades executed — no distribution available.**

---

## 10. Bootstrap / HAC Confidence Intervals

| Metric | 95% CI |
|--------|--------|
| V5 Gross Expectancy | [0.0476, 0.0806] bps |
| V6 Gross Expectancy | [0.0555, 0.0884] bps |
| V5 Net (Taker) | [0.0, 0.0] bps |
| V6 Net (Taker) | [0.0, 0.0] bps |
| V6 Net (Maker) | [-4.01, -4.01] bps |

*Method: HAC (Heteroskedasticity and Autocorrelation Consistent) with max_lag=1*

---

## 11. Statistical Test: Is Expectancy Distinguishable from Zero?

| Test | HAC z | HAC p | Significant (α=0.05)? |
|------|-------|-------|----------------------|
| V5 Gross | 7.61 | 0.000 | **YES** |
| V6 Gross | 8.57 | 0.000 | **YES** |
| V5 Net (Taker) | 0.00 | 1.000 | **NO** |
| V6 Net (Taker) | 0.00 | 1.000 | **NO** |
| V6 Net (Maker) | 0.00 | 1.000 | **NO** |

**Multiple Testing (Bonferroni, 108 experiments, α=0.000463):**
- Gross expectancy: **Passes** (p=0.0 < 0.000463)
- Net expectancy: **FAILS** (p=1.0 > 0.000463)

**Conclusion:** Gross edge is statistically significant but net expectancy is NOT distinguishable from zero.

---

## 12. Stability by Time Period / Regime

| Regime / Period | n | Executed | Gross (bps) | Net (bps) |
|-----------------|---|----------|-------------|-----------|
| First Half | 1,944 | 0 | -0.0062 | 0.0 |
| Second Half | 1,945 | 0 | +0.1346 | 0.0 |
| High Impact Regime | 1,383 | 0 | +0.0020 | 0.0 |
| Normal Regime | 2,506 | 0 | +0.0983 | 0.0 |
| High Vol (Tercile) | 140 | 0 | +0.0467 | 0.0 |
| Low Vol (Tercile) | 3,746 | 0 | +0.0645 | 0.0 |

**No regime produces positive net expectancy.** Gross edge varies but never survives costs.

---

## 13. V5 vs V6 Comparison

| Metric | V5 | V6 | Delta |
|--------|-----|-----|-------|
| Gross Expectancy (bps) | 0.06408 | 0.07192 | +0.00784 |
| Gross 95% CI | [0.0476, 0.0806] | [0.0555, 0.0884] | Overlap |
| Net (Taker) | 0.0 | 0.0 | 0.0 |
| Net (Maker) | N/A | -0.001 | -0.001 |
| Incremental R² | — | 0.000 | 0.000 |
| V5-V6 Correlation | — | 0.552 | — |
| V6 Residual t-stat | — | 7.98 (p=0.000) | — |
| Incremental R² | — | 0.000 | — |

**V6 adds no incremental economic value.** Gross improvement is marginal, CI overlaps, net still zero/negative, incremental R² = 0.0.

---

## 14. Independent Replication

| Item | Status |
|------|--------|
| Protocol Defined | ✅ Yes (`report_11_replication_protocol.json`) |
| Replication Performed | ❌ **NO** |
| Replication Status | **REPLICATION_FAIL** |
| Protocol Requirements | Defined but not executed |

**Independent replication is MANDATORY per protocol — NOT PERFORMED.**

---

## 15. Does Gross Edge Survive Realistic Costs?

| Metric | Value |
|--------|-------|
| V5 Gross Expectancy | 0.0641 bps |
| V6 Gross Expectancy | 0.0719 bps |
| Taker Cost (contemporaneous) | 4.6646 bps |
| Maker Cost (contemporaneous) | 3.4396 bps |
| Cost-to-Gross Ratio (Taker) | 64.9× |
| Cost-to-Gross Ratio (Maker) | 47.8× |
| Net After Taker (V5) | 0.0 bps |
| Net After Taker (V6) | 0.0 bps |
| Net After Maker (V6) | -0.0010 bps |

**Gross edge does NOT survive realistic transaction costs.** Cost-to-gross ratios of 48–73× are economically prohibitive.

---

## 16. Maximum Allowable Round-Trip Cost

| Metric | Value (bps) |
|--------|-------------|
| V5 Max Allowable Cost | 0.06408 |
| V6 Max Allowable Cost | 0.0719 |
| Current Taker Cost | 4.6646 |
| Current Maker Cost | 3.4396 |
| Exceeds Break-Even (Taker) | 72.9× |
| Exceeds Break-Even (Maker) | 53.3× |

**Current costs exceed maximum allowable by 48–73×.**

---

## 17. Final Classification

### **NO_EDGE**

**Reasons:**
1. Zero trades executed in OOS (0/3,889 rows)
2. Net expectancy zero or negative after realistic costs
3. Net expectancy not statistically distinguishable from zero (HAC p=1.0)
4. Cost-to-gross ratio 48–73× exceeds breakeven by 48–73×
4. Break-even cost (0.064–0.072 bps) exceeded by 48–73×
5. Zero directional trades executed (0 LONG, 0 SHORT)
6. V6 adds zero incremental R² over V5
7. Independent replication NOT performed (REPLICATION_FAIL)
8. Multiple testing correction fails for net expectancy
9. No regime shows positive net expectancy
9. Governance lock `V5_BASELINE_NO_LIVE_TRADE = True` remains active

---

## Final Determination

| Dimension | Result |
|-----------|---------|
| **Software Status** | Production-hardened for paper trading (167/167 tests pass) |
| **Economic Status** | **NO_EDGE / REPLICATION_FAIL** |
| **Live Trading** | **HARD-BLOCKED** (governance lock active) |
| **Paper Trading** | Technically ready, economically pointless |

---

## Conclusion

The EXISTING order-flow signal strategy has **no deployable economic edge** after realistic transaction costs. The gross statistical edge is real but economically irrelevant — transaction costs exceed the gross signal by 48–73×. Zero trades execute in OOS. The V6 extension adds zero incremental economic value. Independent replication has not been performed. The V5 governance lock (`V5_BASELINE_NO_LIVE_TRADE = True`) remains scientifically justified and MUST remain active.

**NO_EDGE / REPLICATION_FAIL — Governance lock remains active.**