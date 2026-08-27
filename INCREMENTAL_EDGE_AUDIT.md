# INCREMENTAL EDGE AUDIT

**Date:** 2026-08-26
**Objective:** Measure the incremental predictive information of each candidate variable against the frozen baseline

---

## BASELINE (FROZEN)

| Metric | Value |
|---|---|
| Production SignalEngine gross | +0.174 bps |
| V5 DecisionEngine gross | +0.041 bps |
| Maker cost | 2.0 bps |
| Taker cost | 4.666 bps |
| Net (SignalEngine, maker) | -1.826 bps |
| Net (V5, maker) | -1.959 bps |

---

## INCREMENTAL ANALYSIS

### Methodology
For each candidate variable, we measure:
1. **Standalone gross edge:** Predictive power of the variable alone
2. **Incremental gross edge:** Additional predictive power beyond existing features
3. **Correlation with existing features:** Whether the variable adds new information
4. **Net edge after costs:** Economic viability

### H1: Order-Book Resiliency
| Metric | Value |
|---|---|
| Standalone gross | 0.005 bps |
| Correlation with log_depth1 | 0.85 (high) |
| Incremental information | NONE |
| Net (maker) | -1.995 bps |

**Conclusion:** Resiliency is highly correlated with existing depth features. No incremental value.

### H2: Flow Persistence
| Metric | Value |
|---|---|
| Standalone gross | -0.030 bps (wrong direction) |
| Correlation with tfi_500 | 0.42 (moderate) |
| Incremental information | NONE |
| Net (maker) | -2.030 bps |

**Conclusion:** Flow persistence does not predict returns in the expected direction. No incremental value.

### H3: Depth Concentration
| Metric | Value |
|---|---|
| Standalone gross | -0.006 bps |
| Correlation with qi_l1 | 0.78 (high) |
| Incremental information | NONE |
| Net (maker) | -2.006 bps |

**Conclusion:** Depth concentration is highly correlated with existing queue imbalance. No incremental value.

### H4: Spread Transition
| Metric | Value |
|---|---|
| Standalone gross | 0.303 bps |
| Correlation with spread_bps | 0.15 (low) |
| Incremental information | LOW (few signals) |
| Net (maker) | -1.697 bps |

**Conclusion:** Spread change has some predictive power but too few signals (271) for practical use.

### H5: Price-Impact Normalized Flow
| Metric | Value |
|---|---|
| Standalone gross | 0.367 bps |
| Correlation with tfi_500 | 0.92 (very high) |
| Incremental information | LOW (mostly redundant with TFI) |
| Net (maker) | -1.633 bps |

**Conclusion:** Normalized flow is highly correlated with raw TFI. Limited incremental value.

### H6: Event Clustering
| Metric | Value |
|---|---|
| Standalone gross | 0.022 bps |
| Correlation with log_event_rate | 0.35 (moderate) |
| Incremental information | NONE |
| Net (maker) | -1.978 bps |

**Conclusion:** Event clustering adds no incremental predictive information.

### H7: Large Trade Direction
| Metric | Value |
|---|---|
| Standalone gross | 1.591 bps |
| Correlation with tfi_500 | 0.28 (low) |
| Incremental information | MODERATE (new information) |
| Net (maker) | -0.409 bps |

**Conclusion:** Large trade direction contains genuinely new information not captured by existing features. However, too few signals (885) and still negative net.

---

## INCREMENTAL VALUE RANKING

| Rank | Variable | Incremental Info | Gross (bps) | Net (maker) |
|---|---|---|---|---|
| 1 | Large Trade Direction | MODERATE | 1.591 | -0.409 |
| 2 | Spread Transition | LOW | 0.303 | -1.697 |
| 3 | Normalized Flow | LOW | 0.367 | -1.633 |
| 4 | Event Clustering | NONE | 0.022 | -1.978 |
| 5 | Resiliency | NONE | 0.005 | -1.995 |
| 6 | Depth Concentration | NONE | -0.006 | -2.006 |
| 7 | Flow Persistence | NONE | -0.030 | -2.030 |

---

## CORRELATION MATRIX (Existing vs New Features)

| | qi_l1 | tfi_500 | log_depth1 | spread_bps | log_event_rate |
|---|---|---|---|---|---|
| resiliency_500 | 0.12 | 0.08 | **0.85** | 0.05 | 0.15 |
| flow_persistence | 0.22 | **0.42** | 0.18 | 0.10 | 0.25 |
| depth_concentration | **0.78** | 0.15 | 0.65 | 0.08 | 0.12 |
| spread_change | 0.05 | 0.03 | 0.08 | 0.15 | 0.10 |
| normalized_flow | 0.25 | **0.92** | 0.20 | 0.12 | 0.18 |
| event_clustering | 0.10 | 0.12 | 0.15 | 0.08 | **0.35** |
| large_trade_direction | 0.20 | 0.28 | 0.15 | 0.05 | 0.22 |

**Bold** = high correlation (>0.7) with existing features → limited incremental value

---

## CONCLUSION

Most candidate variables are highly correlated with existing features and provide no incremental predictive information. Only Large Trade Direction contains genuinely new information, but it produces too few signals and still negative net expectancy.

The current information set is **economically insufficient** for live trading.

---

**END OF INCREMENTAL EDGE AUDIT**
