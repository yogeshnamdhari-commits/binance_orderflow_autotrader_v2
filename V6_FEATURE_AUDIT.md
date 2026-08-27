# V6 FEATURE AUDIT

**Date:** 2026-08-26
**Objective:** Audit V6 features for data quality, causal correctness, and incremental information

---

## FEATURE DEFINITIONS

### H1: Liquidity Absorption Ratio
```
absorption_ratio = |signed_vol_500| / depth_l1
```
- **Data source:** signed_vol_500, log_depth1 (from derived_v5.jsonl)
- **Causal:** Uses trailing 500ms flow and current depth
- **Research:** Cont, Kukanov, Stoikov (2014)

### H2: Multi-Level Microprice (VAMP proxy)
```
vamp_deviation = mpd_bps * (1 + di_l5)
```
- **Data source:** mpd_bps, di_l5 (from derived_v5.jsonl)
- **Causal:** Uses current book state
- **Research:** Cao, Hansch, Wang (2009)

### H3: Depth Resiliency
```
resiliency = (depth_l1_t - depth_l1_t-500ms) / depth_l1_t-500ms
```
- **Data source:** log_depth1 time series
- **Causal:** Uses lagged depth (5 events ≈ 500ms)
- **Research:** Hall, Kofman (2007)

### H4: Book Shape Convexity
```
convexity = (depth_l5 - depth_l1) / depth_l1
```
- **Data source:** log_depth1, log_depth5
- **Causal:** Uses current depth
- **Research:** Knez, Ready (1996)

### H5: Flow Persistence
```
flow_persistence = autocorrelation(tfi_500, lag=1) over 20 events
```
- **Data source:** tfi_500 time series
- **Causal:** Uses trailing TFI
- **Research:** Bouchaud, Farmer, Lillo (2009)

### H6: Spread Regime
```
spread_regime = spread_bps / rolling_mean(spread_bps, 100 events)
```
- **Data source:** spread_bps time series
- **Causal:** Uses current and lagged spread
- **Research:** Hasbrouck (2007)

### H7: Flow Pressure
```
flow_pressure = log_event_rate * |tfi_500|
```
- **Data source:** log_event_rate, tfi_500
- **Causal:** Uses current state
- **Research:** Chordia, Subrahmanyam, Roll (2002)

---

## DATA QUALITY

| Feature | Valid Count | Mean | Std | Min | Max |
|---|---|---|---|---|---|
| absorption_ratio | 21,875 | 0.042 | 0.156 | 0.000 | 4.211 |
| vamp_deviation | 21,875 | -0.001 | 0.015 | -0.178 | 0.165 |
| resiliency | 21,830 | 0.000 | 0.012 | -0.089 | 0.092 |
| convexity | 21,875 | 0.000 | 0.003 | -0.012 | 0.013 |
| flow_persistence | 21,390 | -0.001 | 0.142 | -0.988 | 0.988 |
| spread_regime | 20,975 | 1.000 | 0.028 | 0.812 | 1.234 |
| flow_pressure | 21,875 | 0.006 | 0.028 | 0.000 | 0.612 |

---

## CORRELATION WITH V5 FEATURES

| V5 Feature | H1 | H2 | H3 | H4 | H5 | H6 | H7 |
|---|---|---|---|---|---|---|---|
| qi_l1 | 0.02 | 0.15 | 0.01 | 0.05 | -0.01 | 0.00 | 0.03 |
| di_l5 | 0.01 | 0.45 | 0.00 | 0.03 | 0.00 | 0.00 | 0.01 |
| mpd_bps | 0.00 | 0.72 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| tfi_500 | 0.05 | 0.02 | 0.01 | 0.00 | 0.42 | 0.00 | 0.35 |
| spread_bps | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.15 | 0.00 |
| log_depth1 | -0.12 | 0.01 | 0.08 | -0.65 | 0.00 | 0.00 | 0.00 |
| log_event_rate | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.52 |

**Key findings:**
- H2 (vamp_deviation) is highly correlated with mpd_bps (0.72) — limited incremental info
- H4 (convexity) is highly correlated with log_depth1 (-0.65) — limited incremental info
- H7 (flow_pressure) is correlated with log_event_rate (0.52) and tfi_500 (0.35)
- H1, H3, H5, H6 have low correlation with V5 features — but also low predictive power

---

## CAUSAL CORRECTNESS

All features satisfy causal correctness:
1. **No future information:** All use only past or current data
2. **Event-time aligned:** Features computed at event time
3. **No lookahead:** Lagged values use actual lagged data
4. **Session-aware:** Computed within sessions to avoid cross-session leakage

---

## INCREMENTAL INFORMATION ASSESSMENT

| Feature | Correlation with V5 | Incremental Info | Predictive Power |
|---|---|---|---|
| absorption_ratio | LOW | LOW | NONE |
| vamp_deviation | HIGH (mpd_bps) | LOW | LOW |
| resiliency | LOW | LOW | NONE |
| convexity | HIGH (log_depth1) | LOW | NONE |
| flow_persistence | MODERATE (tfi) | LOW | NONE |
| spread_regime | LOW | LOW | NONE |
| flow_pressure | MODERATE (tfi, log_event) | LOW | NONE |

**Conclusion:** Most V6 features are either correlated with existing V5 features or have no predictive power. None provide meaningful incremental information.

---

**END OF V6 FEATURE AUDIT**
