# V6 FINAL DECISION

**Date:** 2026-08-26
**Objective:** Find independently sourced incremental predictive information capable of overcoming realistic BTCUSDT execution costs
**Classification:** **C = NO ROBUST INCREMENTAL EDGE**

---

## BASELINE (FROZEN V5)

| Metric | Value |
|---|---|
| Production SignalEngine gross | +0.174 bps |
| V5 DecisionEngine gross | +0.041 bps |
| Maker cost | 2.0 bps |
| Taker cost | 4.666 bps |
| Net (SignalEngine, maker) | -1.826 bps |

---

## V6 RESULTS SUMMARY

| Feature | Gross (bps) | p-value | Net Maker (bps) | Sessions Positive | Pass Gate |
|---|---|---|---|---|---|
| absorption_ratio | 0.002 | 0.662 | -2.556 | 4/9 | NO |
| vamp_deviation | 0.120 | <0.0001 | -2.438 | 8/9 | NO |
| resiliency | 0.003 | 0.087 | -2.555 | 4/9 | NO |
| convexity | 0.001 | 0.848 | -2.557 | 4/9 | NO |
| flow_persistence | -0.005 | 0.176 | -2.563 | 5/9 | NO |
| spread_regime | 0.001 | 0.771 | -2.557 | 4/9 | NO |
| flow_pressure | 0.002 | 0.662 | -2.556 | 4/9 | NO |

**Bonferroni-corrected α = 0.00714**

---

## EXECUTION SIMULATION (BEST FEATURE: vamp_deviation)

| Metric | Value |
|---|---|
| Gross | 0.120 bps |
| Taker fee | 4.000 bps |
| Maker fee | 2.000 bps |
| Slippage | 0.008 bps |
| Latency | 0.050 bps |
| Adverse selection | 0.500 bps |
| **Net (taker)** | **-4.546 bps** |
| **Net (maker)** | **-2.438 bps** |
| Expected net (maker, 70% fill) | -1.707 bps |
| Break-even cost | 0.120 bps |
| Max adverse | -4.292 bps |
| Max favorable | 3.718 bps |
| Fraction positive | 0.164 |

---

## WALK-FORWARD VALIDATION (vamp_deviation)

| Split | N | Gross (bps) | Net Maker (bps) |
|---|---|---|---|
| 1 | 9,168 | 0.054 | -1.946 |
| 2 | 9,429 | 0.095 | -1.905 |
| 3 | 8,161 | 0.043 | -1.957 |
| 4 | 10,893 | 0.159 | -1.841 |

**All walk-forward splits have negative net edge.**

---

## PERMUTATION CONTROL

| Feature | Actual Gross | Permutation Mean | Incremental |
|---|---|---|---|
| vamp_deviation | 0.120 | -0.005 | +0.125 |
| absorption_ratio | 0.002 | 0.003 | -0.001 |
| resiliency | 0.003 | 0.000 | +0.003 |
| convexity | 0.001 | 0.001 | +0.000 |
| flow_persistence | -0.005 | 0.001 | -0.006 |
| spread_regime | 0.001 | 0.001 | +0.000 |
| flow_pressure | 0.002 | 0.003 | -0.001 |

Only vamp_deviation shows meaningful incremental information over permutation.

---

## WHY V6 FAILS THE ECONOMIC GAP

1. **Signal magnitude too small:** Best gross = 0.120 bps vs maker cost = 2.0 bps
2. **Gap is 16.7x:** Would need 16.7x improvement to break even
3. **All features correlated with existing V5 features:** Limited incremental information
4. **Execution costs dominate:** Even with 70% fill probability, net remains deeply negative

---

## COMPARISON: V5 vs V6

| Metric | V5 Baseline | V6 Best (vamp_deviation) | Improvement |
|---|---|---|---|
| Gross | 0.174 bps | 0.120 bps | -0.054 bps |
| Net (maker) | -1.826 bps | -2.438 bps | -0.612 bps |
| Sessions positive | 23/26 | 8/9 | comparable |

**V6 does NOT improve over V5 baseline.**

---

## INFORMATION SET CONCLUSION

The current BTCUSDT order-flow information set does NOT contain enough predictive information to produce economically viable trading signals, even when augmented with 7 research-backed microstructure variables:

1. **Order-book resiliency:** No incremental predictive power
2. **Multi-level microprice:** Statistically significant but economically insignificant
3. **Book shape:** No incremental predictive power
4. **Flow persistence:** No incremental predictive power
5. **Spread regime:** No incremental predictive power
6. **Flow pressure:** No incremental predictive power
7. **Liquidity absorption:** No incremental predictive power

---

## FINAL CLASSIFICATION

### **C = NO ROBUST INCREMENTAL EDGE**

No V6 feature produces positive net expectancy after realistic execution costs. The information gap cannot be closed by further feature engineering on the existing BTCUSDT order-flow data.

---

## RECOMMENDATION

1. **Do NOT modify production V5**
2. **Keep V5_BASELINE_NO_LIVE_TRADE = True**
3. **Live trading remains BLOCKED**
4. **To achieve viability, additional data sources are required:**
   - Cross-venue data (Coinbase, Kraken, OKX)
   - Liquidation feeds (paid subscription)
   - Higher-frequency data (<100ms)
   - Alternative data (on-chain, sentiment)

---

## DELIVERABLES

- V6_RESEARCH_PLAN.md
- V6_FEATURE_AUDIT.md (this document)
- V6_OOS_AUDIT.md (walk-forward results)
- V6_EXECUTION_AUDIT.md (execution simulation)
- app/v6_features.py
- app/v6_research.py
- app/v6_validation.py
- app/v6_execution.py
- data/research/v6_feature_results.csv
- data/research/v6_oos_results.csv
- data/research/v6_execution_results.csv

---

**END OF V6 FINAL DECISION**
