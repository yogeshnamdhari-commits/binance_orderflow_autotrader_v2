# V9 Final Research Report — Cross-Asset Lead-Lag Predictability

**Date:** 2026-08-31
**Status:** COMPLETE
**Verdict:** **FALSIFIED**

---

## 1. Hypothesis

**H1 (V9 Cross-Asset Lead-Lag):** The lagged returns of Bitcoin (BTC) predict the returns of altcoins at horizons of 5–15 minutes, and this predictability generates positive net expectancy after current Binance execution costs when traded as a long-short portfolio across altcoins.

**H0 (Null):** After accounting for current Binance execution costs, the expected net return of a cross-asset lead-lag strategy is ≤ 0.

---

## 2. Experiment Summary

| Property | Value |
|----------|-------|
| Model | Ridge regression (α=0.05) |
| Predictors | 6 (BTC lagged returns, OFI, realized vol) |
| Target | Equal-weighted altcoin 5-min forward return |
| Horizons | 5, 10, 15 minutes |
| Universe | 10 altcoins (ETH, SOL, BNB, XRP, ADA, AVAX, DOT, LINK, POL, DOGE) |
| Common data range | 2026-05-31 to 2026-08-15 (76 days) |
| Walk-forward | 30-day train / 10-day val / 10-day OOS / 10-day step |
| Total OOS folds | 9 (3 per horizon) |
| Cost per rebalance | 85 bps (base case) |

---

## 3. Out-of-Sample Results

### 3.1 Per-Horizon Results

| Horizon | Folds | Avg Gross (bps) | Avg Net (bps) | Avg t-stat | % Positive |
|---------|-------|-----------------|---------------|------------|------------|
| 5 min | 3 | +0.018 | **-84.98** | -581.5 | 0% |
| 10 min | 3 | -0.185 | **-85.18** | -321.1 | 0% |
| 15 min | 3 | -0.291 | **-85.29** | -228.2 | 0% |

### 3.2 Per-Fold Detail

| Horizon | Fold | OOS Period | Gross (bps) | Net (bps) | t-stat |
|---------|------|------------|-------------|-----------|--------|
| 5m | 1 | 2026-07-10 to 07-20 | +0.081 | -84.92 | -503.2 |
| 5m | 2 | 2026-07-20 to 07-30 | +0.197 | -84.80 | -581.1 |
| 5m | 3 | 2026-07-30 to 08-09 | -0.223 | -85.22 | -660.3 |
| 10m | 1 | 2026-07-10 to 07-20 | +0.094 | -84.91 | -269.1 |
| 10m | 2 | 2026-07-20 to 07-30 | -0.237 | -85.24 | -304.6 |
| 10m | 3 | 2026-07-30 to 08-09 | -0.411 | -85.41 | -389.8 |
| 15m | 1 | 2026-07-10 to 07-20 | -0.149 | -85.15 | -173.4 |
| 15m | 2 | 2026-07-20 to 07-30 | -0.352 | -85.35 | -240.7 |
| 15m | 3 | 2026-07-30 to 08-09 | -0.373 | -85.37 | -270.5 |

---

## 4. Falsification Assessment

| Criterion | Threshold | Result | Status |
|-----------|-----------|--------|--------|
| Primary endpoint | Net > 0, CI excl. zero, t > 3.0 | Net = -85 bps, t < -200 | **FAIL** |
| Consistency | Positive in ≥ 60% of folds | 0% positive | **FAIL** |
| Cost sensitivity | Net > 0 at 2× costs | Net = -170 bps at 2× | **FAIL** |
| Permutation control | Return > 95th percentile of null | Not exceeded | **FAIL** |

**All four falsification criteria are met.**

---

## 5. Permutation Control

| Metric | Value |
|--------|-------|
| Actual avg net return | -85.15 bps |
| Permutation 95th percentile | -85.15 bps |
| Actual > 95th percentile | **No** |
| Permutation mean | -85.15 bps |

The strategy's performance is indistinguishable from random permutation of the near-zero gross returns.

---

## 6. Root Cause Analysis

The V9 hypothesis fails because:

1. **Gross edge is essentially zero:** Average gross return across all folds and horizons is -0.15 bps (range: -0.41 to +0.20 bps). This is economically meaningless.

2. **Transaction costs dominate:** At 85 bps per rebalance, costs are 500× larger than the gross edge.

3. **No cross-asset predictability at minute horizons:** The BTC lagged returns, OFI, and realized volatility do not predict altcoin returns at 5-15 minute horizons in this dataset.

4. **Literature result does not replicate:** Guo et al. (2024) reported 3.55 bps/min spread using 2019-2021 data. Our 2026 data shows no such predictability. This suggests the cross-asset lead-lag effect may have decayed as markets became more efficient.

---

## 7. Limitations

| Limitation | Impact |
|------------|--------|
| Only 76 days of common data | Reduced number of OOS folds (3 vs. required 5) |
| 30-day training window (vs. 60 in spec) | Less training data per fold |
| Single model (Ridge) | Did not test LASSO/PCA |
| Simplified signal construction | Used sign(prediction) without threshold optimization |

**Note:** The result is so unequivocal (0% positive folds, -85 bps net) that these limitations do not affect the conclusion.

---

## 8. Comparison with Prior Versions

| Version | Gross (bps) | Net (bps) | Verdict |
|---------|-------------|-----------|---------|
| V5 (500ms taker) | +0.064 | -4.55 | REJECTED |
| V6 (liquidity provision) | +0.280 | -2.44 | FALSIFIED |
| V7 (cross-market) | N/A | N/A | UNTESTABLE |
| V8 (trade-flow) | +0.464 | -2.04 | REJECTED |
| **V9 (cross-asset lead-lag)** | **-0.15** | **-85.15** | **FALSIFIED** |

V9's gross edge is actually negative (unlike V5-V8 which had slightly positive gross edges), and the per-rebalance cost is higher due to the multi-asset portfolio construction.

---

## 9. Final Verdict

### **FALSIFIED**

The V9 cross-asset lead-lag hypothesis is **rejected**. The evidence shows:

1. No predictable cross-asset information at 5-15 minute horizons
2. Gross returns are essentially zero (-0.41 to +0.20 bps)
3. After realistic transaction costs (85 bps/rebalance), net returns are deeply negative (-85 bps)
4. 0% of OOS folds are positive
5. Permutation control confirms the result is indistinguishable from random

---

## 10. Conclusion

The project now has **three independent negative results**:
- **V5:** Single-asset order flow at 500ms → no edge after costs
- **V6:** Liquidity provision at 1-30s → no edge after costs
- **V9:** Cross-asset lead-lag at 5-15min → no edge after costs

All tested information sets (order flow, queue dynamics, cross-asset returns) fail to produce economically viable trading signals on Binance BTCUSDT under realistic execution costs.

---

## 11. Implementation Status

| Status | Value |
|--------|-------|
| Economically viable | **NO** |
| Implementation authorized | **NO** |
| Live trading authorized | **NO** |

---

## 12. Next Authorized Action

No further action is required for V9. The hypothesis has been tested and falsified.

If a new research direction is desired, it should be designated **V10** and begin with a new literature review and hypothesis specification. Potential directions include:
- Longer horizons (hours to days)
- Different instruments (spot vs. futures)
- Alternative data sources (on-chain, sentiment)
- Cross-venue arbitrage (requires new data)

---

*Report completed: 2026-08-31*
*Experiment: app/v9_experiment.py*
*Results: data/research/v9_oos_results.json*
*Permutation: data/research/v9_permutation_test.json*
