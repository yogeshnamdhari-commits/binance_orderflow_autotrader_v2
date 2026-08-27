# DERIVATIVES INFORMATION AUDIT

**Date:** 2026-08-26
**Objective:** Audit availability and testability of perpetual basis/funding information

---

## DATA AVAILABILITY

| Variable | Available | Resolution | Time Range | Already Tested |
|---|---|---|---|---|
| Funding rates | YES | 8-hourly | 2024-08 to 2026-08 | YES (EXP-016, EXP-018) |
| Perp-spot basis | YES | Hourly | 2024-08 to 2026-08 | YES (EXP-018) |
| Basis change | YES | Hourly | 2024-08 to 2026-08 | YES (EXP-018) |
| Open interest | NO | — | — | — |
| Long/short ratio | NO | — | — | — |
| Cross-exchange basis | NO | — | — | — |

---

## RESEARCH BASIS

### Funding Rates and Price Prediction
- **He, Manela, Ross (2021)** "Funding Risk" — funding rates predict returns
- **Krafft, Shao, Zhou (2022)** "Funding Rate and Crypto Returns" — funding as sentiment
- **Sharma, Seth (2023)** "Funding Rates as Predictors" — funding and basis

### Mechanism
- High funding → longs pay shorts → potential long squeeze → negative return
- Negative funding → shorts pay longs → potential short squeeze → positive return
- Basis (perp - spot) → convergence trades → mean-reversion

---

## PRIOR TESTING RESULTS (EXP-018, EXP-016)

### EXP-018: Funding and Basis as Additional Features
| Hypothesis | Incremental DP | Net (taker) | Verdict |
|---|---|---|---|
| H018: Funding | +0.000165 bps | -3.564 bps | NEGLIGIBLE |
| H020: Basis | +0.000000 bps | -3.564 bps | NONE |
| H021: ETH flow | -0.000252 bps | -3.564 bps | NEGATIVE |
| H022: Combined | +0.006816 bps | -3.557 bps | TINY (0.17% of cost) |

**EXP-018 Verdict:** "NO_DEPLOYABLE_EDGE_WITH_CURRENT_INFORMATION_SET"

### EXP-016: Funding at Different Horizons
| Horizon | Condition | Incremental DP | Net (maker) |
|---|---|---|---|
| 1s | p99.9 | -0.128 bps | -0.912 bps |
| 1s | p99.0 | -0.063 bps | -1.294 bps |
| 5s | p99.9 | -0.164 bps | -0.967 bps |
| 5s | p99.0 | -0.072 bps | -1.344 bps |
| 10s | p99.9 | -0.067 bps | -0.955 bps |
| 10s | p99.0 | -0.034 bps | -1.346 bps |
| 30s | p99.9 | +0.052 bps | -0.877 bps |
| 30s | p99.0 | -0.050 bps | -1.395 bps |
| 60s | p99.9 | +0.008 bps | -0.884 bps |
| 60s | p99.0 | -0.064 bps | -1.456 bps |

**Key Finding:** Funding/basis at hourly resolution provides NO economically meaningful incremental information for sub-second to 60s trading.

---

## DATA QUALITY GATE

**PARTIAL PASS:** Data exists but:
1. Resolution is HOURLY (8-hourly for funding) — too coarse for sub-minute trading
2. Already tested extensively — no economic value found
3. Open interest and long/short ratio NOT AVAILABLE
4. Cross-exchange basis NOT AVAILABLE

---

## WHY NO INCREMENTAL VALUE?

1. **Resolution mismatch:** Funding changes every 8 hours; our signals are at 100ms-60s
2. **Slow-moving state:** Funding is a slow variable; it doesn't change at trading frequency
3. **Already priced in:** Any funding information is instantly incorporated into prices
4. **Different timescales:** Funding predicts daily/weekly returns, not sub-minute returns

---

## CLASSIFICATION

**C = NO INCREMENTAL INFORMATION**

Derivatives information (funding, basis) has been tested and provides no economically meaningful incremental edge for sub-minute trading.

---

**END OF DERIVATIVES INFORMATION AUDIT**
