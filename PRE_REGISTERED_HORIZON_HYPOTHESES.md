# PRE-REGISTERED HORIZON HYPOTHESES

**Date:** 2026-08-25
**Objective:** Measure the information decay curve of the existing order-flow signal across multiple holding horizons
**Method:** Evaluate pre-registered horizons on chronological OOS data using frozen signal generation

---

## Pre-Registered Horizons

| ID | Horizon | Description |
|---|---|---|
| H1 | 100 ms | Ultra-short (1 depth update) |
| H2 | 250 ms | Short (2-3 depth updates) |
| H3 | 500 ms | Current primary horizon (5 depth updates) |
| H4 | 1 s | Medium (10 depth updates) |
| H5 | 2 s | Medium-long (20 depth updates) |
| H6 | 5 s | Long (50 depth updates) |
| H7 | 10 s | Very long (100 depth updates) |
| H8 | 30 s | Extended (300 depth updates) |
| H9 | 60 s | Maximum (600 depth updates) |

---

## Signal Generation (UNCHANGED)

- **Production SignalEngine:** delta > 0 & imbalance_5 > 0.20 → BUY; delta < 0 & imbalance_5 < -0.20 → SELL
- **Frozen V5 DecisionEngine:** calibrated prediction > 0 → BUY; < 0 → SELL
- **Features:** Same 17 V5 features, same 4 SignalEngine features
- **No horizon-specific optimization**

---

## Target Definition (Causal)

For a signal at timestamp `ts_ms` and horizon `H`:

```
target_return(H) = (mid(ts_ms + H) - mid(ts_ms)) / mid(ts_ms) * 1e4  [bps]
```

- `mid(ts_ms + H)` is the first mid price at or after `ts_ms + H`
- Only information occurring AFTER `ts_ms` is used
- No future book states as features
- No overlapping target leakage

---

## Metrics (Per Horizon)

| # | Metric | Description |
|---|---|---|
| 1 | Raw directional gross return | Sign-matched return |
| 2 | Mid-price return | Raw mid-price change |
| 3 | Bid/ask executable return | Return at executable prices |
| 4 | Market-order net return | Gross - taker cost |
| 5 | Maker net return | Gross - maker cost |
| 6 | Signal count | Number of signals evaluated |
| 7 | Fraction positive | Fraction with gross > 0 |
| 8 | Mean | Average gross return |
| 9 | Median | Median gross return |
| 10 | Standard deviation | Return volatility |
| 11 | t-statistic | One-sample t-test vs 0 |
| 12 | 95% confidence interval | Block-bootstrap CI |
| 13 | Per-session results | Session-level breakdown |
| 14 | Per-regime results | Regime-level breakdown |
| 15 | Maximum adverse excursion | Worst-case drawdown |
| 16 | Maximum favorable excursion | Best-case gain |
| 17 | Time-to-peak | Time to maximum favorable |
| 18 | Time-to-adverse-move | Time to maximum adverse |
| 19 | Spread at signal | Book spread at signal time |
| 20 | Volatility at signal | Realized vol at signal time |

---

## Economic Test

For each horizon:

```
Net(H) = ExecutableGrossReturn(H) - RealisticExecutionCost
BreakEvenCost(H) = GrossEdge(H)
```

Compare BreakEvenCost(H) against:
- Maker cost (2.0 bps)
- Taker cost (4.016 bps)
- Observed spread (0.016 bps)
- Observed slippage (0.008 bps)

---

## Controls

| Control | Description |
|---|---|
| Unconditional market return | Average mid-price change over horizon H |
| Signed random entry | Random BUY/SELL with same signal count |
| Time-matched control | Returns at random times matching signal times |
| Signal-direction permutation | Permute signal directions within sessions |

---

## Multiple-Hypothesis Correction

- **Number of horizons:** 9
- **Correction method:** Bonferroni (α = 0.05/9 = 0.00556)
- **Confidence level:** 99.444% for individual tests

---

## Pre-Registered Decision Rules

- **Classification A (No viable edge):** No horizon has net > 0 with p < 0.00556
- **Classification B (Predictive but insufficient):** Longer horizon has gross > 0 with p < 0.00556 but net < 0
- **Classification C (Viable edge):** Longer horizon has net > 0 with p < 0.00556 AND survives controls
- **Classification D (Invalid):** Data cannot support causal horizon evaluation

---

## Data Resolution Audit

- **Source:** Binance USD-M futures @depth@100ms
- **Typical depth updates:** ~10 per second
- **Typical trades:** ~5-50 per second
- **Minimum feasible horizon:** ~100ms (1 depth update)
- **Maximum feasible horizon:** ~600s (full session length)

All 9 pre-registered horizons are feasible with the available data.

---

## OOS Evaluation Protocol

- **Training sessions:** 20260818-190746 to 20260818-195221 (12 sessions)
- **OOS sessions:** 20260818-212451 to 20260818-232919 (15 sessions)
- **Signal generation:** Frozen (no re-fitting)
- **Target computation:** Causal (only post-signal information)
