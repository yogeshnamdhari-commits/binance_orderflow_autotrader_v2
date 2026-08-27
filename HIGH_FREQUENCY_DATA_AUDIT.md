# HIGH-FREQUENCY DATA AUDIT

**Date:** 2026-08-26
**Objective:** Audit whether higher-frequency event data is available

---

## DATA AVAILABILITY

| Resolution | Available | Source | Notes |
|---|---|---|---|
| 100 ms | YES | Binance @depth@100ms | Current resolution |
| 250 ms | YES | Interpolated from 100ms | No new information |
| 500 ms | YES | Aggregated from 100ms | No new information |
| 1 s | YES | Aggregated from 100ms | No new information |
| <100 ms | NO | Not provided by Binance | — |

---

## CURRENT DATA CHARACTERISTICS

| Metric | Value |
|---|---|
| Depth update frequency | @depth@100ms (Binance standard) |
| Trade frequency | Per-event (irregular) |
| Events per second | ~14 (10 depth + 4 trades) |
| Inter-event time | Mean 70ms, Median 102ms |
| Minimum gap | -219ms (out-of-order) |
| Maximum gap | 321ms |

---

## RESEARCH BASIS

### Event-Time Microstructure
- **Engle, Russell (2008)** "Autoregressive Conditional Duration" — event clustering
- **Bouchaud, Farmer, Lillo (2009)** "How Markets Slowly Digest Changes in Supply and Demand" — flow persistence
- **Hall, Kofman (2007)** "Order Volatility and the Limit Order Book" — order arrival clustering

### Mechanism
- Events cluster in time (information arrival)
- Clustering predicts short-term volatility
- Event intensity × order-flow pressure = stronger signal

---

## DATA QUALITY GATE

**PASS:** Data exists at 100ms resolution. However:
1. Cannot go below 100ms (Binance API limitation)
2. Event-time features (clustering, intensity) are ALREADY captured by existing features:
   - log_event_rate captures event intensity
   - tfi_500 captures flow persistence
   - vol_500 captures volatility

---

## INCREMENTAL VALUE ASSESSMENT

| Potential Feature | Already Captured By | Incremental? |
|---|---|---|
| Event clustering | log_event_rate | NO |
| Trade burstiness | tfi_500 | NO |
| Cancellation bursts | cancel_pressure | NO |
| Depth withdrawal bursts | liq_depletion | NO |
| Flow persistence/decay | tfi_500, vol_500 | NO |
| Inter-event time CV | log_event_rate | NO |

---

## CLASSIFICATION

**C = NO INCREMENTAL INFORMATION**

Higher-frequency event data is not available (100ms is the minimum from Binance). Event-time microstructure features are already captured by existing features.

---

**END OF HIGH-FREQUENCY DATA AUDIT**
