# ALPHA DISCOVERY RESULTS

**Date:** 2026-08-26
**Objective:** Determine whether the current information set is missing a microstructure variable capable of producing economically meaningful edge
**Baseline:** Frozen production implementation (unchanged)

---

## RESULTS SUMMARY

| ID | Name | N Signals | Gross (bps) | p-value | Net Maker (bps) | Pass Gate |
|---|---|---|---|---|---|---|
| H1 | Order-Book Resiliency | 6,551 | 0.005 | 0.208 | -1.995 | NO |
| H2 | Flow Persistence | 5,759 | -0.030 | 0.015 | -2.030 | NO |
| H3 | Depth Concentration | 6,557 | -0.006 | 0.499 | -2.006 | NO |
| H4 | Spread Change | 271 | 0.303 | <0.0001 | -1.697 | NO |
| H5 | Normalized Flow | 5,976 | 0.367 | <0.0001 | -1.633 | NO |
| H6 | Event Clustering | 6,473 | 0.022 | 0.127 | -1.978 | NO |
| H7 | Large Trade Direction | 885 | 1.591 | <0.0001 | -0.409 | NO |

**Bonferroni-corrected α = 0.00714**

**FINAL: NO hypothesis passes the economic gate.**

---

## DETAILED RESULTS

### H1: Order-Book Resiliency
- **Research:** Cont, Kukanov, Stoikov (2014)
- **Variable:** resiliency_500 = depth change over 500ms
- **Signals:** 6,551
- **Gross:** 0.005 bps (not significant, p=0.208)
- **Net (maker):** -1.995 bps
- **Sessions positive:** 4/9
- **Conclusion:** No incremental predictive information

### H2: Flow Persistence
- **Research:** Bouchaud, Farmer, Lillo (2009)
- **Variable:** flow_persistence = autocorrelation of TFI
- **Signals:** 5,759
- **Gross:** -0.030 bps (significant but wrong direction, p=0.015)
- **Net (maker):** -2.030 bps
- **Sessions positive:** 4/9
- **Conclusion:** Flow persistence does not help; high persistence actually predicts reversal

### H3: Depth Concentration
- **Research:** Cao, Hansch, Wang (2009)
- **Variable:** depth_concentration = depth_l1 / depth_l5
- **Signals:** 6,557
- **Gross:** -0.006 bps (not significant, p=0.499)
- **Net (maker):** -2.006 bps
- **Sessions positive:** 2/8
- **Conclusion:** No incremental predictive information; correlated with existing qi_l1

### H4: Spread Transition
- **Research:** Hasbrouck (2007)
- **Variable:** spread_change = spread_t - spread_t-500ms
- **Signals:** 271 (few signals)
- **Gross:** 0.303 bps (significant, p<0.0001)
- **Net (maker):** -1.697 bps
- **Sessions positive:** 6/8
- **Conclusion:** Statistically significant but too few signals for practical use

### H5: Price-Impact Normalized Flow
- **Research:** Cont, Kukanov, Stoikov (2014)
- **Variable:** normalized_flow = tfi_500 / log_depth5
- **Signals:** 5,976
- **Gross:** 0.367 bps (significant, p<0.0001)
- **Net (maker):** -1.633 bps
- **Sessions positive:** 7/9
- **Conclusion:** Statistically significant but insufficient magnitude

### H6: Event Clustering
- **Research:** Engle, Russell (2008)
- **Variable:** event_clustering = CV of inter-event times
- **Signals:** 6,473
- **Gross:** 0.022 bps (not significant, p=0.127)
- **Net (maker):** -1.978 bps
- **Sessions positive:** 4/9
- **Conclusion:** No incremental predictive information

### H7: Large Trade Direction
- **Research:** Easley, O'Hara (1987)
- **Variable:** large_trade_direction = direction of largest trade in 500ms
- **Signals:** 885 (few signals)
- **Gross:** 1.591 bps (significant, p<0.0001)
- **Net (maker):** -0.409 bps
- **Sessions positive:** 6/9
- **Conclusion:** Highest gross edge but still negative net; too few signals

---

## KEY FINDINGS

### 1. Large Trade Direction is the Most Promising
- Gross edge of 1.591 bps is the highest of any variable tested
- Statistically significant (p<0.0001)
- But only 885 signals (too few for practical trading)
- Net (maker) = -0.409 bps (still negative)

### 2. The Economic Gap Remains
- Best net (maker) = -0.409 bps (H7)
- Maker cost = 2.0 bps
- Gap = 0.409 bps (still significant)

### 3. Most New Variables Add No Value
- H1, H2, H3, H6: Not statistically significant
- H4, H5: Significant but insufficient magnitude
- Only H7 shows meaningful predictive power

### 4. The Information Set is Economically Insufficient
- No variable produces positive net expectancy
- The gap between signal magnitude and execution costs persists
- Additional microstructure variables do not close the gap

---

## ROBUSTNESS

### Session Stability
| Hypothesis | Sessions Positive | Total Sessions |
|---|---|---|
| H4: Spread Change | 6/8 | 75% |
| H5: Normalized Flow | 7/9 | 78% |
| H7: Large Trade Direction | 6/9 | 67% |

### Signal Count
- H7 has only 885 signals across 9 OOS sessions (~98 per session)
- This is too few for practical trading after costs

---

## CONCLUSION

The current BTCUSDT order-flow information set, even when augmented with 7 research-backed microstructure variables, does not contain enough predictive information to produce economically viable trading signals.

The closest candidate (Large Trade Direction) achieves gross 1.591 bps but:
1. Has too few signals (885 total)
2. Still produces negative net expectancy (-0.409 bps maker)
3. The gap to economic viability remains

**Recommendation:** Obtain additional data sources rather than further optimizing the existing model.

---

**END OF ALPHA DISCOVERY RESULTS**
