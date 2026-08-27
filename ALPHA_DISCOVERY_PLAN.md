# ALPHA DISCOVERY PLAN — INFORMATION-SET EXPANSION

**Date:** 2026-08-26
**Objective:** Determine whether the current information set is fundamentally missing a microstructure variable capable of producing economically meaningful edge
**Baseline:** Frozen production implementation (unchanged)

---

## CURRENT INFORMATION SET (AUDIT)

### Existing Features
| Feature | Description | Source |
|---|---|---|
| ofi_l1 | Order flow imbalance at L1 | CKS |
| ofi_norm_l1 | OFI / depth1 | CKS |
| qi_l1 | Queue imbalance at touch | Cont et al. |
| di_l5, di_l10 | Distance-weighted depth imbalance | Cont et al. |
| mpd_bps | Microprice deviation | Multiple |
| spread_bps | Bid-ask spread | Standard |
| bid_cancel_bps, ask_cancel_bps | Cancel pressure | Event |
| bid_add_bps, ask_add_bps | Add pressure | Event |
| cancel_pressure | Total cancel pressure | Event |
| tfi_500 | Trade flow imbalance (500ms) | Chordia et al. |
| liq_depletion | Near-touch depth consumed | Event |
| log_depth1, log_depth5 | Log liquidity | Standard |
| log_event_rate | Event activity | Standard |
| depth_slope_bps | Log-depth decay | Book shape |
| vol_500 | Realized volatility (500ms) | Standard |

### Known Gaps
1. **No order-book resiliency measure** — recovery after aggressive trades
2. **No trade-level aggressor dynamics** — burstiness, persistence
3. **No multi-level shape** — only L1, L5, L10 aggregates
4. **No liquidity transition detection** — spread widening, depth withdrawal
5. **No flow decay estimation** — half-life of order-flow information
6. **No price-impact normalization** — flow / available liquidity
7. **No event-time microstructure** — arrival clustering

---

## PRE-REGISTERED HYPOTHESES

### H1: Order-Book Resiliency (Depth Recovery)

**Research Basis:**
- Cont, Kukanov, Stoikov (2014) "Price Impact of Order Book Events" — depth recovery predicts future liquidity
- Hall, Kofman (2007) "Order Volatility and the Limit Order Book" — resiliency as liquidity measure
- Cao, Hansch, Wang (2009) "The Information Content of an Open Limit-Order Book" — book resilience predicts returns

**Mechanism:**
After an aggressive trade consumes depth, the speed at which liquidity replenishes indicates whether the trade was informed (slow recovery) or uninformed (fast recovery). Fast recovery → mean-reversion; slow recovery → continuation.

**Variable Definition:**
```
resiliency_500 = (depth_500ms_after_trade - depth_at_trade) / depth_at_trade
Measured over 500ms window after each aggressive trade
Positive = replenished, Negative = further depleted
```

**Causal Construction:**
- Measure depth at trade time
- Measure depth 500ms after trade
- Compute ratio
- Use as feature at next signal time

**Expected Direction:**
High resiliency → mean-reversion (opposite of trade direction)
Low resiliency → continuation (same direction as trade)

**Falsification:**
If resiliency has no correlation with future returns, hypothesis fails.

---

### H2: Trade Flow Persistence (Signed Flow Decay)

**Research Basis:**
- Chordia, Subrahmanyam, Roll (2002) "Order Imbalance, Liquidity, and Market Returns" — flow persistence predicts short-term returns
- Cont, Bouchaud, Potters (2007) "Scaling in Stock Market Data" — order flow autocorrelation decays as power law
- Bouchaud, Farmer, Lillo (2009) "How Markets Slowly Digest Changes in Supply and Demand" — price impact decay

**Mechanism:**
Order flow is autocorrelated. Recent signed flow predicts near-future signed flow. The decay rate of this autocorrelation determines the optimal holding period.

**Variable Definition:**
```
flow_persistence = autocorrelation(tfi_500, lag=1)
Computed over rolling window of 100 events
Range: [-1, 1]
Positive = flow persists, Negative = flow mean-reverts
```

**Causal Construction:**
- Compute TFI over 500ms windows
- Compute autocorrelation over last 100 windows
- Use as feature at signal time

**Expected Direction:**
High persistence → current flow direction continues
Low persistence → current flow direction reverses

**Falsification:**
If flow persistence has no correlation with future returns, hypothesis fails.

---

### H3: Multi-Level Depth Concentration

**Research Basis:**
- Cao, Hansch, Wang (2009) "The Information Content of an Open Limit-Order Book" — multi-level depth predicts returns
- Boulatov, George (2013) "Hidden and Displayed Liquidity" — depth concentration matters
- Knez, Ready (1996) "Estimating the Profits from Trading Strategies" — multi-level information

**Mechanism:**
Current features use L1, L5, L10 aggregates. But the *distribution* of depth across levels contains information. Concentrated depth at top levels indicates strong support/resistance; dispersed depth indicates weak levels.

**Variable Definition:**
```
depth_concentration = depth_l1 / depth_l5
Range: [0, 1]
High = concentrated at top, Low = dispersed
```

**Causal Construction:**
- Use existing depth_l1 and depth_l5 from derived data
- Compute ratio at signal time

**Expected Direction:**
High concentration → strong support/resistance at touch
Low concentration → weak levels, easier to move price

**Falsification:**
If depth concentration has no correlation with future returns, hypothesis fails.

---

### H4: Spread Transition (Liquidity Regime Change)

**Research Basis:**
- Hasbrouck (2007) "Empirical Market Microstructure" — spread changes predict volatility
- Huang, Stoll (1997) "The Components of the Bid-Ask Spread" — spread components
- Menkveld, Wang (2013) "How Do Designated Market Makers Create Value?" — spread transitions

**Mechanism:**
The spread is not static. Transitions from narrow to wide spread indicate increasing adverse selection. The *change* in spread is more informative than the level.

**Variable Definition:**
```
spread_change = spread_bps - spread_bps_500ms_ago
Positive = widening (more adverse), Negative = narrowing
```

**Causal Construction:**
- Measure spread at signal time
- Measure spread 500ms before signal time
- Compute difference

**Expected Direction:**
Widening spread → avoid trading (higher adverse selection)
Narrowing spread → safer to trade

**Falsification:**
If spread change has no correlation with future returns, hypothesis fails.

---

### H5: Price-Impact Normalized Flow

**Research Basis:**
- Cont, Kukanov, Stoikov (2014) "Price Impact of Order Book Events" — price impact inversely related to depth
- Goyenko, Holden, Trzcinka (2009) "Do Liquidity Measures Measure Liquidity?" — normalized flow
- Chordia, Subrahmanyam, Roll (2002) — order imbalance normalized by liquidity

**Mechanism:**
The same order flow has different price impact depending on available liquidity. A 1 BTC trade in a thin book moves price more than in a thick book. Normalizing flow by depth should increase signal-to-noise.

**Variable Definition:**
```
normalized_flow = tfi_500 / log_depth5
Range: [-inf, inf]
High = flow relative to available liquidity
```

**Causal Construction:**
- Use existing tfi_500 and log_depth5
- Compute ratio at signal time

**Expected Direction:**
High normalized flow → stronger signal (more flow per unit liquidity)
Low normalized flow → weaker signal

**Falsification:**
If normalized flow has lower correlation with future returns than raw TFI, hypothesis fails.

---

### H6: Event-Time Microstructure (Arrival Clustering)

**Research Basis:**
- Engle, Russell (2008) "Autoregressive Conditional Duration" — event clustering
- Hall, Kofman (2007) — order arrival clustering
- Bouchaud, Farmer, Lillo (2009) — order flow clustering

**Mechanism:**
Events (trades, depth updates) do not arrive uniformly. Clustering of events indicates information arrival. The intensity of event arrivals predicts short-term volatility and direction.

**Variable Definition:**
```
event_clustering = std(inter_event_times) / mean(inter_event_times)
Computed over last 50 events
High = clustered (bursty), Low = uniform
```

**Causal Construction:**
- Compute inter-event times over last 50 events
- Compute coefficient of variation
- Use as feature at signal time

**Expected Direction:**
High clustering → information arrival → stronger signal
Low clustering → random noise → weaker signal

**Falsification:**
If event clustering has no correlation with future returns, hypothesis fails.

---

### H7: Large Trade Arrival (Informed Trading Proxy)

**Research Basis:**
- Easley, O'Hara (1987) "Price, Trade Size, and Information in Securities Markets" — large trades are informed
- Lee, Ready (1991) "Inferring Trade Direction from Intraday Data" — trade size
- Chordia, Subrahmanyam, Roll (2002) — order imbalance

**Mechanism:**
Large trades are more likely to be informed. The arrival of a large trade (top decile by size) signals information. The direction of large trades predicts short-term returns.

**Variable Definition:**
```
large_trade_direction = sign of largest trade in last 500ms
+1 if buyer-initiated, -1 if seller-initiated
0 if no large trades
```

**Causal Construction:**
- Identify trades in last 500ms
- Find largest trade by size
- Use its direction as feature

**Expected Direction:**
Large buyer-initiated trade → bullish signal
Large seller-initiated trade → bearish signal

**Falsification:**
If large trade direction has no correlation with future returns, hypothesis fails.

---

## HYPOTHESIS REGISTRATION TABLE

| ID | Name | Research Basis | Variable | Alpha |
|---|---|---|---|---|
| H1 | Order-Book Resiliency | Cont et al. (2014) | resiliency_500 | 0.00714 |
| H2 | Flow Persistence | Chordia et al. (2002) | flow_persistence | 0.00714 |
| H3 | Depth Concentration | Cao et al. (2009) | depth_concentration | 0.00714 |
| H4 | Spread Transition | Hasbrouck (2007) | spread_change | 0.00714 |
| H5 | Normalized Flow | Cont et al. (2014) | normalized_flow | 0.00714 |
| H6 | Event Clustering | Engle, Russell (2008) | event_clustering | 0.00714 |
| H7 | Large Trade Arrival | Easley, O'Hara (1987) | large_trade_direction | 0.00714 |

**Total hypotheses:** 7
**Bonferroni-corrected α:** 0.00714
**Evaluation period:** Chronological OOS (sessions 212451-232919)

---

## ECONOMIC ACCEPTANCE GATE

A hypothesis passes only if ALL of the following are true:

1. Gross edge > 0 AND p < 0.00714 (Bonferroni-corrected)
2. Net edge (maker) > 0 AFTER realistic execution costs
3. Session stability: > 60% of sessions have positive gross
4. Not concentrated in a single session or regime
5. Confidence interval lower bound > 0
6. Incremental to frozen baseline (not just correlated with existing features)

If no hypothesis passes all conditions, the information set is classified as ECONOMICALLY INSUFFICIENT.

---

## WHAT CONSTITUTES FAILURE

A hypothesis FAILS if:
- Gross edge is not statistically significant (p > 0.00714)
- Net edge (maker) is negative
- Results are concentrated in < 4 sessions
- The effect disappears in permutation control
- The variable is highly correlated with existing features (no incremental info)

---

## NO PARAMETER FISHING

The following are PROHIBITED:
- Adjusting thresholds after seeing results
- Testing multiple parameter combinations
- Selecting the best-looking specification
- Adding features beyond the 7 pre-registered hypotheses
- Changing the OOS evaluation period

If all 7 hypotheses fail, we STOP and report ECONOMICALLY INSUFFICIENT.
