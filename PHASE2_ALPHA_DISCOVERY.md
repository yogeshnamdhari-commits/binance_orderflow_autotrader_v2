# PHASE 2: CROSS-MARKET / DERIVATIVES / FORCED-FLOW INFORMATION AUDIT

**Date:** 2026-08-26
**Objective:** Determine whether missing economic information comes from outside Binance BTCUSDT local order book

---

## SUMMARY TABLE

| Information Source | Data Available | Causal? | Incremental Gross | Incremental Net | OOS Significant? | Economically Viable? |
|---|---|---|---|---|---|---|
| Cross-market price discovery | NO | — | — | — | — | D = UNAVAILABLE |
| Liquidation flow | NO | — | — | — | — | D = UNAVAILABLE |
| Perpetual basis/funding | YES (hourly) | YES | +0.007 bps | -3.550 bps | NO | C = NO VALUE |
| Higher-frequency events | NO (>100ms) | — | — | — | — | C = NO VALUE |

---

## DETAILED FINDINGS

### 1. Cross-Market Price Discovery — UNTESTABLE
- **Data:** Only Binance BTCUSDT available at high frequency
- **Research:** Brandvoll (2021), Karkkainen (2022) — lead-lag in crypto
- **Gap:** No cross-venue historical data available
- **Classification:** D = DATA UNAVAILABLE

### 2. Liquidation Flow — UNTESTABLE
- **Data:** NOT AVAILABLE (requires paid subscription)
- **Research:** Brunnermeier, Pedersen (2005); Antoniou et al. (2023)
- **Gap:** No reliable historical liquidation data
- **Classification:** D = DATA UNAVAILABLE

### 3. Perpetual Basis / Funding — TESTED, NO VALUE
- **Data:** Available at hourly resolution (8-hourly for funding)
- **Research:** He, Manela, Ross (2021); Krafft et al. (2022)
- **Already tested:** EXP-016, EXP-018
- **Results:** Incremental DP = +0.007 bps (0.17% of taker cost)
- **Net (taker):** -3.550 bps (still deeply negative)
- **Why no value:** Resolution mismatch (hourly vs sub-minute), slow-moving state
- **Classification:** C = NO INCREMENTAL INFORMATION

### 4. Higher-Frequency Event Information — NOT AVAILABLE
- **Data:** 100ms is minimum from Binance API
- **Research:** Engle, Russell (2008); Bouchaud et al. (2009)
- **Already captured:** log_event_rate, tfi_500, vol_500, cancel_pressure
- **Classification:** C = NO INCREMENTAL INFORMATION

---

## CONCLUSION

**No external information source provides economically meaningful incremental edge.**

The data quality gate eliminates most hypotheses:
- Cross-venue: DATA UNAVAILABLE
- Liquidations: DATA UNAVAILABLE
- Basis/funding: Available but already tested — NO INCREMENTAL VALUE
- Higher-frequency: Already at maximum available resolution

The current BTCUSDT order-flow information set, even when augmented with derivatives context (funding, basis), does not contain enough predictive information to produce economically viable trading signals.

---

## FINAL CLASSIFICATION

**C = NO INCREMENTAL INFORMATION**

No external information source closes the economic gap.

---

**END OF PHASE 2 ALPHA DISCOVERY**
