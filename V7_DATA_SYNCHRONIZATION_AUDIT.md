# V7 DATA SYNCHRONIZATION AUDIT

**Date:** 2026-08-27
**Objective:** Audit cross-market data availability and timestamp quality for V7

---

## EXECUTIVE SUMMARY

**V7 (cross-market price discovery) is largely UNTESTABLE with available data.**

Only Binance BTCUSDT data is available at sufficient resolution. No cross-venue data exists for Coinbase, Kraken, Bybit, OKX, or CME.

---

## DATA AVAILABILITY BY VENUE

| Venue | Available | Resolution | Time Range | Usable for V7? |
|---|---|---|---|---|
| Binance BTCUSDT spot | YES | Per-trade (aggTrades) | 2024-08 to 2026-08 | Baseline only |
| Binance BTCUSDT perp | YES | 100ms depth | 2026-08-18 | Baseline only |
| Coinbase BTC/USD | NO | — | — | NOT AVAILABLE |
| Kraken BTC/USD | NO | — | — | NOT AVAILABLE |
| Bybit BTCUSDT | NO | — | — | NOT AVAILABLE |
| OKX BTCUSDT | NO | — | — | NOT AVAILABLE |
| CME BTC futures | NO | — | — | NOT AVAILABLE |

---

## AVAILABLE BINANCE DATA (DETAILED)

### aggTrades (Per-Trade Resolution)
| Property | Value |
|---|---|
| Files | 730 daily parquet files |
| Date range | 2024-08-16 to 2026-08-15 |
| Total size | 21.13 GB |
| Columns | agg_trade_id, price, quantity, first_trade_id, last_trade_id, transact_time, is_buyer_maker |
| Timestamp resolution | Milliseconds |
| Trades per day | ~140,000 - 200,000 |

### Depth Updates
| Property | Value |
|---|---|
| Source | Binance @depth@100ms |
| Resolution | 100ms |
| Date range | 2026-08-18 (27 sessions) |
| Sessions | 27 |

### Derivatives
| Property | Value |
|---|---|
| Funding rates | 8-hourly (too coarse) |
| Hourly price | Hourly (too coarse) |
| Perp/Spot hourly | Hourly (too coarse) |

---

## DATA QUALITY GATE

### Cross-Market Data: FAIL
- **No cross-venue data available**
- Only Binance data exists
- Cannot test lead-lag between venues
- Cannot test cross-venue dislocation
- Cannot test information share

### Liquidation Data: FAIL
- **Not available**
- Binance does not provide historical liquidation data
- Third-party providers require paid subscriptions

### Higher-Frequency Data: PASS (but only Binance)
- **aggTrades at millisecond resolution available**
- 21 GB of trade-level data
- But only for Binance (no cross-market)

### Derivatives Data: PARTIAL FAIL
- **Available but too coarse**
- Hourly resolution insufficient for sub-minute trading
- Already tested in EXP-016/EXP-018 — no economic value

---

## TIMESTAMP QUALITY ASSESSMENT

### Binance aggTrades Timestamps
- **Resolution:** Milliseconds
- **Semantics:** Exchange trade time (transact_time)
- **Quality:** High (direct from Binance)
- **Clock sync:** N/A (single venue)

### Cross-Venue Timestamps
- **Not applicable** — no cross-venue data

---

## WHAT CANNOT BE TESTED

| Hypothesis | Reason |
|---|---|
| H1: Cross-Venue Lead-Lag | No cross-venue data |
| H2: Information Share | No cross-venue data |
| H3: Cross-Venue Dislocation | No cross-venue data |
| H4: Cross-Venue Flow Divergence | No cross-venue data |
| H5: Perp-Spot Basis Lead | Hourly resolution too coarse |
| H6: Liquidation Pressure | No liquidation data |

---

## WHAT COULD BE TESTED (but is not cross-market)

The available Binance aggTrades data could be used for:
1. **Trade-level flow analysis** — but this is single-venue
2. **Trade size analysis** — but this is single-venue
3. **Liquidity absorption** — but this is single-venue
4. **Event-time microstructure** — but this is single-venue

These are NOT cross-market hypotheses and do not address the V7 objective.

---

## CONCLUSION

**V7 (cross-market price discovery) is UNTESTABLE with available data.**

The data quality gate fails for all 6 pre-registered hypotheses:
- No cross-venue data available
- No liquidation data available
- Derivatives data too coarse

---

## CLASSIFICATION

**D = DATA INSUFFICIENT FOR V7**

Cross-market price discovery cannot be tested. The required data (Coinbase, Kraken, Bybit, OKX, CME historical trade data at sub-second resolution) is not available.

---

**END OF V7 DATA SYNCHRONIZATION AUDIT**
