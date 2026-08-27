# INFORMATION SET AUDIT

**Date:** 2026-08-26
**Objective:** Document current information set and identify gaps

---

## CURRENT INFORMATION SET

### Raw Data Available
| Data Type | Resolution | Source |
|---|---|---|
| Depth updates | @depth@100ms | Binance WebSocket |
| Trades | Per-event | Binance WebSocket |
| Book snapshots | Per-event | REST + WebSocket |
| Top-10 levels | Per-event | Replayed |

### Derived Features (Current)
| Feature | Computation | Information Class |
|---|---|---|
| ofi_l1 | Sum of signed qty deltas at L1 | Order flow |
| ofi_norm_l1 | ofi_l1 / depth1 | Normalized flow |
| qi_l1 | (bq - aq) / (bq + aq) | Queue imbalance |
| di_l5, di_l10 | Distance-weighted imbalance | Multi-level imbalance |
| mpd_bps | (microprice - mid) / mid | Microprice |
| spread_bps | (ask - bid) / mid | Spread |
| bid_cancel_bps, ask_cancel_bps | Cancel qty / mid | Cancel pressure |
| bid_add_bps, ask_add_bps | Add qty / mid | Add pressure |
| cancel_pressure | (bid_cancels + ask_cancels) / depth1 | Cancel pressure |
| tfi_500 | (buy_vol - sell_vol) / total_vol | Trade flow |
| liq_depletion | trade_vol / depth5 | Liquidity depletion |
| log_depth1, log_depth5 | log(1 + depth) | Liquidity level |
| log_event_rate | log(1 + event_count) | Activity |
| depth_slope_bps | log-depth decay | Book shape |
| vol_500 | Realized volatility | Volatility |

---

## INFORMATION GAPS IDENTIFIED

### Gap 1: Order-Book Resiliency
**Current state:** No measure of depth recovery after trades
**Research:** Cont, Kukanov, Stoikov (2014)
**Potential variable:** resiliency_500 = depth_recovery / depth_consumed

### Gap 2: Flow Persistence/Decay
**Current state:** No measure of order flow autocorrelation
**Research:** Bouchaud, Farmer, Lillo (2009)
**Potential variable:** flow_persistence = autocorrelation(tfi, lag=1)

### Gap 3: Multi-Level Shape
**Current state:** Only L1, L5, L10 aggregates
**Research:** Cao, Hansch, Wang (2009)
**Potential variable:** depth_concentration = depth_l1 / depth_l5

### Gap 4: Liquidity Transitions
**Current state:** No detection of spread/depth regime changes
**Research:** Hasbrouck (2007)
**Potential variable:** spread_change = spread_t - spread_t-500ms

### Gap 5: Price-Impact Normalization
**Current state:** TFI not normalized by available liquidity
**Research:** Cont, Kukanov, Stoikov (2014)
**Potential variable:** normalized_flow = tfi_500 / log_depth5

### Gap 6: Event-Time Microstructure
**Current state:** No measure of event arrival clustering
**Research:** Engle, Russell (2008)
**Potential variable:** event_clustering = std(inter_event_times) / mean(inter_event_times)

### Gap 7: Large Trade Information
**Current state:** No distinction between large and small trades
**Research:** Easley, O'Hara (1987)
**Potential variable:** large_trade_direction = direction of largest recent trade

---

## DATA AVAILABILITY FOR NEW VARIABLES

| Variable | Required Data | Available | Feasible |
|---|---|---|---|
| resiliency_500 | Depth at trade time + 500ms after | YES (derived_v5 has levels) | YES |
| flow_persistence | TFI time series | YES (can compute from derived_v5) | YES |
| depth_concentration | depth_l1, depth_l5 | YES (in derived_v5) | YES |
| spread_change | spread_bps time series | YES (in derived_v5) | YES |
| normalized_flow | tfi_500, log_depth5 | YES (in derived_v5) | YES |
| event_clustering | inter-event times | YES (from ts_ms) | YES |
| large_trade_direction | trade sizes | PARTIAL (signed_vol_500 only) | PARTIAL |

---

## EXPECTED INFORMATIONAL VALUE

| Variable | Expected Incremental Value | Rationale |
|---|---|---|
| resiliency_500 | MEDIUM | Captures post-trade dynamics not in current features |
| flow_persistence | LOW-MEDIUM | May help optimize holding period |
| depth_concentration | LOW | Correlated with existing qi_l1, di_l5 |
| spread_change | MEDIUM | Regime detection could filter bad signals |
| normalized_flow | MEDIUM | Better signal-to-noise than raw TFI |
| event_clustering | LOW | May be correlated with log_event_rate |
| large_trade_direction | HIGH | Large trades are informed (Easley, O'Hara) |

---

**END OF INFORMATION SET AUDIT**
