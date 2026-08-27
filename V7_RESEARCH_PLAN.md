# V7 RESEARCH PLAN — CROSS-MARKET PRICE DISCOVERY

**Date:** 2026-08-27
**Objective:** Determine whether information arriving in another BTC market/venue predicts subsequent Binance BTCUSDT move strongly enough to overcome realistic execution costs
**Status:** Pre-registered before evaluation

---

## GATE (PRE-REGISTERED)

PRIMARY CRITERION: NET_OOS_BPS_AFTER_REALISTIC_EXECUTION > 0

A candidate passes only if ALL of the following are true:
1. Positive net OOS edge after realistic execution costs
2. Economically meaningful effect size (> 0.5 bps net)
3. Statistical evidence after multiple-testing correction
4. Stability across independent sessions (> 60% positive)
5. Stability across regimes
6. Persistence in untouched final OOS
7. Robustness to realistic execution assumptions

If no configuration passes: **NO_DEPLOYABLE_EDGE_WITH_CURRENT_INFORMATION_SET**

If data is insufficient: **DATA_INSUFFICIENT_FOR_V7**

---

## DATA AVAILABILITY REQUIREMENTS

### Required for V7
| Data Type | Minimum Resolution | Source |
|---|---|---|
| BTCUSDT spot (Binance) | 100ms depth | Available |
| BTCUSDT perpetual (Binance) | 100ms depth | Available |
| BTC/USD spot (Coinbase) | 100ms trades | UNKNOWN |
| BTC/USD spot (Kraken) | 100ms trades | UNKNOWN |
| BTCUSDT perpetual (Bybit) | 100ms trades | UNKNOWN |
| BTCUSDT perpetual (OKX) | 100ms trades | UNKNOWN |
| CME BTC futures | 100ms trades | UNKNOWN |
| Liquidation data | Event-level | UNKNOWN |

### Data Already Available (from Phase 2 Audit)
| Data Type | Resolution | Source | Usable? |
|---|---|---|---|
| BTCUSDT spot depth | 100ms | Binance | YES |
| BTCUSDT perp depth | 100ms | Binance | YES |
| Funding rates | 8-hourly | Binance | NO (too coarse) |
| Hourly price | Hourly | Binance | NO (too coarse) |
| Liquidation data | — | — | NOT AVAILABLE |

---

## PRE-REGISTERED HYPOTHESES

### H1: Cross-Venue Lead-Lag Returns
**Research Basis:**
- Hasbrouck (1995) "One Security, Many Markets" — price discovery
- Huang (2002) "The Quality of ECN and NASDAQ Market Maker Quotes" — lead-lad
- Lehmann (2002) "Some Desirability of Cross-Market Surveillance" — cross-market info

**Hypothesis:** Returns in leading markets (e.g., Coinbase spot) predict returns in Binance BTCUSDT within 100ms-5s.

**Data Required:** Coinbase/Kraken trade data at 100ms resolution.

**Falsification:** If lead-lag correlation is not statistically significant, hypothesis fails.

### H2: Information Share / Component Share
**Research Basis:**
- Hasbrouck (1995) — Information Share
- Harris, McInish, Shoesmith (2002) — Component Share
- Putnis (2013) — Leadership Share

**Hypothesis:** Cross-venue information share predicts short-term Binance BTCUSDT returns.

**Data Required:** Synchronized multi-venue trade data.

**Falsification:** If information share has no predictive power, hypothesis fails.

### H3: Cross-Venue Price Dislocation
**Research Basis:**
- Foucault, Kozhan, Tham (2017) "Toxic Flow" — cross-market dislocation
- Menkveld, Wang (2013) — cross-market liquidity

**Hypothesis:** Deviation from common efficient price predicts Binance BTCUSDT mean-reversion.

**Data Required:** Synchronized multi-venue mid-prices.

**Falsification:** If dislocation does not predict mean-reversion, hypothesis fails.

### H4: Cross-Venue Order Flow Divergence
**Research Basis:**
- Chordia, Subrahmanyam, Roll (2002) — order imbalance
- Boulatov, George (2013) — cross-market flow

**Hypothesis:** Divergence in signed flow between venues predicts Binance BTCUSDT direction.

**Data Required:** Multi-venue trade sign data.

**Falsification:** If flow divergence has no predictive power, hypothesis fails.

### H5: Perp-Spot Basis Lead
**Research Basis:**
- He, Manela, Ross (2021) — funding risk
- Krafft, Shao, Zhou (2022) — basis and returns

**Hypothesis:** Changes in perp-spot basis predict Binance BTCUSDT returns.

**Data Required:** Synchronized perp and spot prices at sub-minute resolution.

**Falsification:** If basis changes have no predictive power, hypothesis fails.

### H6: Liquidation Pressure
**Research Basis:**
- Brunnermeier, Pedersen (2005) — predatory trading
- Antoniou, Tarashev, Tsomidis (2023) — liquidation impact

**Hypothesis:** Liquidation bursts predict Binance BTCUSDT short-term reversals.

**Data Required:** Timestamped liquidation data.

**Falsification:** If liquidation pressure has no predictive power, hypothesis fails.

---

## HORIZONS (PRE-REGISTERED)

| Horizon | Description |
|---|---|
| 100 ms | Ultra-short |
| 250 ms | Short |
| 500 ms | Current V5 horizon |
| 1 s | Medium |
| 2 s | Medium-long |
| 5 s | Long |
| 10 s | Very long |
| 30 s | Extended |

---

## VALIDATION PROTOCOL

1. Chronological walk-forward with purge/embargo
2. Untouched final OOS period (last 20% of sessions)
3. Session-level statistics
4. Regime-level statistics
5. Newey-West/HAC inference
6. Block bootstrap (block_size=50, 2000 iterations)
7. Permutation control (direction permutation within sessions)
8. Compare against V5 baseline, V6 result, unconditional return

---

## MULTIPLE-TESTING CORRECTION

- **Method:** Bonferroni (conservative, pre-specified)
- **Number of hypotheses:** 6
- **Corrected α:** 0.05 / 6 = 0.00833

---

## EXECUTION ASSUMPTIONS (FROZEN)

| Parameter | Value | Source |
|---|---|---|
| Taker fee (round-trip) | 4.0 bps | Binance |
| Maker fee (round-trip) | 2.0 bps | Binance |
| Slippage (p90, 1K notional) | 0.008 bps | Measured |
| Latency cost | 0.050 bps | Measured |
| Adverse selection | 0.500 bps | Estimated |
| Fill probability (maker) | 70% | Measured |
| Total maker cost | 2.558 bps | Sum |

---

## WHAT CONSTITUTES FAILURE

A hypothesis FAILS if:
- p > 0.00833 (Bonferroni-corrected)
- Net edge (maker) < 0
- Positive session fraction < 60%
- Effect disappears in permutation control
- Data is insufficient

If all 6 fail: **NO_DEPLOYABLE_EDGE_WITH_CURRENT_INFORMATION_SET**

---

## DATA QUALITY GATE

Before testing any hypothesis, verify:
1. Historical availability at required resolution
2. Timestamp resolution and semantics
3. Clock synchronization across venues
4. Missing data patterns
5. Exchange outages
6. Duplicate events
7. Stale quotes
8. Asynchronous observations
9. API reconstruction bias

If reliable historical data cannot be obtained: **DATA_INSUFFICIENT_FOR_V7**

---

**END OF V7 RESEARCH PLAN**
