# V6 RESEARCH PLAN

**Date:** 2026-08-26
**Status:** Pre-registered before evaluation
**Objective:** Find independently sourced incremental predictive information capable of overcoming realistic BTCUSDT execution costs

---

## GATE (PRE-REGISTERED)

NET_EDGE = GROSS_EDGE - FEES - SLIPPAGE - MARKET_IMPACT - LATENCY_COST - EXPECTED_ADVERSE_SELECTION

DEPLOY only if:
1. NET OOS EDGE > 0
2. Lower 95% confidence bound > 0 where statistically appropriate
3. Survives multiple-testing correction
4. Positive across a meaningful fraction of independent sessions
5. Remains positive under realistic execution assumptions
6. Survives untouched final OOS

If no configuration passes: **NO_DEPLOYABLE_EDGE_WITH_CURRENT_INFORMATION_SET**

---

## DATA AVAILABILITY (FROM PHASE 2 AUDIT)

| Information Class | Available | Source |
|---|---|---|
| Multi-venue flow | NO | Only Binance data exists |
| Liquidation pressure | NO | Requires paid subscription |
| Liquidity/Absorption | YES | Existing depth data (L1/L5/L10) |
| Microprice (L5/VAMP) | YES | Existing depth data |
| Regime variables | YES | Existing data |

**Conclusion:** V6 focuses on information extractable from existing BTCUSDT depth data that V5 does NOT capture.

---

## V5 vs V6 INFORMATION DIFFERENCE

### V5 Captures
- Static imbalance: qi_l1, di_l5, di_l10
- Aggregate flow: ofi_l1, tfi_500
- Simple state: spread_bps, log_depth1/5, vol_500

### V6 Tests (NOT in V5)
- **Liquidity dynamics:** absorption, replenishment, resilience
- **Multi-level microprice:** VAMP, volume-weighted pressure
- **Book shape:** convexity, concentration, slope beyond L1
- **Regime detection:** when signals are reliable
- **Flow dynamics:** persistence, decay, clustering

---

## PRE-REGISTERED HYPOTHESES

### H1: Liquidity Absorption Ratio

**Research Basis:**
- Cont, Kukanov, Stoikov (2014) "Price Impact of Order Book Events" — price impact inversely related to depth
- Boulatov, George (2013) "Hidden and Displayed Liquidity" — absorption capacity

**Mechanism:**
Aggressive trades that consume depth have different price impact depending on available liquidity. The ratio of aggressive flow to near-touch depth predicts whether the impact will be temporary (absorbed) or permanent.

**Variable:**
```
absorption_ratio = signed_vol_500 / depth_l1
High ratio = flow exceeds absorption capacity → permanent impact
Low ratio = flow absorbed → temporary impact
```

**Information available at decision time:** signed_vol_500 (trailing 500ms), depth_l1 (current)

**Expected Direction:**
High absorption_ratio → continuation (direction of flow)
Low absorption_ratio → mean-reversion

**Falsification:**
If absorption_ratio has no correlation with future returns, hypothesis fails.

---

### H2: Multi-Level Microprice (VAMP)

**Research Basis:**
- Cao, Hansch, Wang (2009) "The Information Content of an Open Limit-Order Book" — multi-level information
- Stoikov (2020) "The Microstructure of Financially Illiquid Assets" — volume-weighted average mid-price

**Mechanism:**
V5 uses L1 microprice (mpd_bps). But information exists at multiple levels. The Volume-weighted Average Micro-Price (VAMP) across L1-L10 captures the full book pressure.

**Variable:**
```
VAMP = sum(price_level * qty_level) / sum(qty_level) for levels 1-10
VAMP_deviation = (VAMP - mid) / mid * 1e4
```

**Information available at decision time:** All level data from derived_v5.jsonl

**Expected Direction:**
VAMP > mid → bullish pressure
VAMP < mid → bearish pressure

**Falsification:**
If VAMP_deviation has lower correlation with future returns than mpd_bps, hypothesis fails.

---

### H3: Depth Resiliency (Recovery Rate)

**Research Basis:**
- Hall, Kofman (2007) "Order Volatility and the Limit Order Book" — resilience as liquidity measure
- Cont, Kukanov, Stoikov (2014) — depth recovery predicts future liquidity

**Mechanism:**
After depth is consumed, the speed of replenishment indicates whether liquidity providers support the current price. Fast recovery = support; slow recovery = rejection.

**Variable:**
```
resiliency = (depth_l1_t - depth_l1_t_minus_500ms) / depth_l1_t_minus_500ms
Positive = replenished, Negative = further depleted
```

**Information available at decision time:** depth_l1 time series

**Expected Direction:**
High resiliency → current price level supported → tradeable
Low resiliency → price level unsupported → avoid trading

**Falsification:**
If resiliency has no correlation with future returns, hypothesis fails.

---

### H4: Book Shape Convexity

**Research Basis:**
- Knez, Ready (1996) "Estimating the Profits from Trading Strategies" — multi-level information
- Boulatov, George (2013) — depth concentration

**Mechanism:**
The SHAPE of the book (not just aggregates) contains information. Convex book (more depth at higher levels) indicates strong support. Concave book (less depth at higher levels) indicates weak support.

**Variable:**
```
convexity = (depth_l5 - depth_l1) / depth_l1
High = convex (deep levels), Low = concave (shallow levels)
```

**Information available at decision time:** depth_l1, depth_l5

**Expected Direction:**
Convex book → strong support → safer to trade
Concave book → weak support → riskier to trade

**Falsification:**
If convexity has no correlation with future returns, hypothesis fails.

---

### H5: Flow Persistence (Autocorrelation)

**Research Basis:**
- Bouchaud, Farmer, Lillo (2009) "How Markets Slowly Digest Changes in Supply and Demand" — order flow autocorrelation decays as power law
- Cont, Bouchaud, Potters (2007) "Scaling in Stock Market Data" — flow persistence

**Mechanism:**
Order flow is autocorrelated. The current autocorrelation of TFI indicates whether recent flow is persisting (trending) or mean-reverting. This helps determine whether to trade with or against recent flow.

**Variable:**
```
flow_persistence = autocorrelation(tfi_500, lag=1) over last 20 events
Range: [-1, 1]
Positive = flow persists, Negative = flow mean-reverts
```

**Information available at decision time:** TFI time series

**Expected Direction:**
High persistence → trade WITH recent flow
Low persistence → trade AGAINST recent flow (mean-reversion)

**Falsification:**
If flow_persistence has no correlation with future returns, hypothesis fails.

---

### H6: Spread Regime Detection

**Research Basis:**
- Hasbrouck (2007) "Empirical Market Microstructure" — spread changes predict volatility
- Huang, Stoll (1997) "The Components of the Bid-Ask Spread" — spread components
- Menkveld, Wang (2013) — spread transitions

**Mechanism:**
The spread is not static. Transitions from narrow to wide spread indicate increasing adverse selection. Signals during wide-spread regimes are less reliable.

**Variable:**
```
spread_regime = spread_bps / rolling_mean(spread_bps, 100 events)
High = wide spread (avoid), Low = narrow spread (trade)
```

**Information available at decision time:** spread_bps time series

**Expected Direction:**
Wide spread → avoid trading (higher adverse selection)
Narrow spread → safer to trade

**Falsification:**
If spread regime does not predict signal quality, hypothesis fails.

---

### H7: Flow Intensity × Order-Flow Pressure

**Research Basis:**
- Chordia, Subrahmanyam, Roll (2002) — order imbalance
- Engle, Russell (2008) — event clustering

**Mechanism:**
The interaction between event intensity and order-flow pressure captures "bursty" flow. High intensity + high pressure = information arrival. Low intensity = noise.

**Variable:**
```
flow_pressure = log_event_rate * |tfi_500|
High = intense informed flow, Low = noise
```

**Information available at decision time:** log_event_rate, tfi_500

**Expected Direction:**
High flow_pressure → strong signal
Low flow_pressure → weak signal (avoid)

**Falsification:**
If flow_pressure has no correlation with signal quality, hypothesis fails.

---

## HYPOTHESIS REGISTRATION TABLE

| ID | Name | Research Basis | Variable | Alpha |
|---|---|---|---|---|
| H1 | Liquidity Absorption | Cont et al. (2014) | absorption_ratio | 0.00714 |
| H2 | Multi-Level Microprice | Cao et al. (2009) | VAMP_deviation | 0.00714 |
| H3 | Depth Resiliency | Hall, Kofman (2007) | resiliency | 0.00714 |
| H4 | Book Shape Convexity | Knez, Ready (1996) | convexity | 0.00714 |
| H5 | Flow Persistence | Bouchaud et al. (2009) | flow_persistence | 0.00714 |
| H6 | Spread Regime | Hasbrouck (2007) | spread_regime | 0.00714 |
| H7 | Flow Pressure | Chordia et al. (2002) | flow_pressure | 0.00714 |

**Total hypotheses:** 7
**Bonferroni-corrected α:** 0.00714

---

## MULTIPLE-TESTING CORRECTION

- **Method:** Bonferroni (conservative, pre-specified)
- **Corrected α:** 0.05 / 7 = 0.00714
- **Secondary check:** Benjamini-Hochberg FDR at q=0.05

---

## VALIDATION PROTOCOL

1. Chronological split: 60% train / 40% OOS
2. Walk-forward with purge/embargo
3. Untouched final OOS period (last 20% of sessions)
4. Session-level results
5. Regime-level results
6. Moving-block bootstrap (block_size=50, 2000 iterations)
7. Permutation control (direction permutation within sessions)
8. Compare against V5 baseline
9. Compare against unconditional return

---

## EXECUTION ASSUMPTIONS (FROZEN)

| Parameter | Value | Source |
|---|---|---|
| Taker fee (round-trip) | 4.0 bps | Binance |
| Maker fee (round-trip) | 2.0 bps | Binance |
| Slippage (p90, 1K notional) | 0.008 bps | Measured |
| Latency cost | 0.05 bps | Measured |
| Safety margin | 0.5 bps | Pre-registered |
| Total taker gate | 4.666 bps | Measured |
| Total maker cost | 2.0 bps | Measured |

---

## WHAT CONSTITUTES FAILURE

A hypothesis FAILS if:
- p > 0.00714 (Bonferroni-corrected)
- Net edge (maker) < 0
- Positive session fraction < 60%
- Effect disappears in permutation control
- Confidence interval includes zero

If all 7 fail: **NO_DEPLOYABLE_EDGE_WITH_CURRENT_INFORMATION_SET**

---

## NO PARAMETER FISHING

- No threshold adjustment after seeing results
- No multiple parameter combinations
- No best-looking specification selection
- No adding features beyond 7 pre-registered

---

**END OF V6 RESEARCH PLAN**
