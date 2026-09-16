# V9 Data Acquisition Specification

**Date:** 2026-08-31
**Status:** AUTHORIZED (per V9_PRE_DATA_REAUDIT.md)
**Authority:** MASTER_GOVERNANCE_PROTOCOL.md (commit `1f9a667`)

---

## 1. Purpose

Acquire the altcoin minute-level trade data required to test the V9 cross-asset lead-lag hypothesis. The BTC predictor data already exists locally.

---

## 2. Symbol Universe

| Rank | Symbol | Tier | Liquidity Multiplier |
|------|--------|------|---------------------|
| 1 | ETHUSDT | 1 | 2× |
| 2 | SOLUSDT | 1 | 2× |
| 3 | BNBUSDT | 1 | 2× |
| 4 | XRPUSDT | 2 | 3× |
| 5 | ADAUSDT | 2 | 3× |
| 6 | AVAXUSDT | 2 | 3× |
| 7 | DOTUSDT | 2 | 3× |
| 8 | LINKUSDT | 3 | 5× |
| 9 | MATICUSDT | 3 | 5× |
| 10 | DOGEUSDT | 3 | 5× |

---

## 3. Data Requirements

| Property | Specification |
|----------|---------------|
| Market type | USDⓈ-M Futures (perpetual) |
| Data type | aggTrades (aggregated trades) |
| Minimum date range | 90 days (2026-05-31 to 2026-08-30) |
| Ideal date range | 730 days (2024-08-30 to 2026-08-30) |
| Required resolution | Per-trade (millisecond timestamps) |
| Required fields | timestamp, price, quantity, is_buyer_maker |
| Timestamp convention | UTC milliseconds |
| Synchronization | All symbols use same UTC minute boundaries |
| Missing-data tolerance | ≤ 5% invalid bars per coin per training window |

---

## 4. Source

| Source | URL | Method |
|--------|-----|--------|
| Binance Vision (public) | https://data.binance.vision/?prefix=data/futures/um/daily/aggTrades/ | HTTPS download |
| Binance API (fallback) | https://fapi.binance.com/fapi/v1/aggTrades | REST (rate-limited) |

**Primary method:** Binance Vision daily ZIP files (same format as existing BTC archives)

**URL pattern:**
```
https://data.binance.vision/data/futures/um/daily/aggTrades/{SYMBOL}/{SYMBOL}-aggTrades-{YYYY-MM-DD}.zip
```

---

## 5. Storage Format

| Property | Specification |
|----------|---------------|
| Raw storage | `data/hist/archives/{SYMBOL}/aggTrades/` (ZIP files, preserved) |
| Normalized storage | `data/hist/normalized/{SYMBOL}/aggTrades/` (Parquet, one per day) |
| Format | Parquet (same schema as BTCUSDT) |
| Schema | `agg_trade_id, price, quantity, first_trade_id, last_trade_id, transact_time, is_buyer_maker` |
| Timezone | UTC |
| Duplicate-safe | Yes (via agg_trade_id) |
| Gap-detected | Yes (daily file presence check) |

---

## 6. Expected Storage Requirements

| Symbol | Est. Daily Size | 90-Day Total | 730-Day Total |
|--------|----------------|--------------|---------------|
| ETHUSDT | ~15 MB | ~1.4 GB | ~10.5 GB |
| SOLUSDT | ~10 MB | ~0.9 GB | ~6.8 GB |
| BNBUSDT | ~8 MB | ~0.7 GB | ~5.5 GB |
| XRPUSDT | ~6 MB | ~0.5 GB | ~4.2 GB |
| ADAUSDT | ~5 MB | ~0.5 GB | ~3.5 GB |
| AVAXUSDT | ~4 MB | ~0.4 GB | ~2.8 GB |
| DOTUSDT | ~3 MB | ~0.3 GB | ~2.1 GB |
| LINKUSDT | ~3 MB | ~0.3 GB | ~2.1 GB |
| MATICUSDT | ~3 MB | ~0.3 GB | ~2.1 GB |
| DOGEUSDT | ~3 MB | ~0.3 GB | ~2.1 GB |
| **Total** | **~60 MB/day** | **~5.5 GB** | **~41.7 GB** |

---

## 7. Validation Requirements

| Check | Method | Threshold |
|-------|--------|-----------|
| File completeness | Count daily files | 100% of expected dates |
| Schema validation | Check column names | Match BTCUSDT schema |
| Timestamp continuity | Check for gaps | No gaps > 1 hour |
| Duplicate detection | agg_trade_id uniqueness | 0 duplicates |
| Price sanity | Min/max price vs reference | Within 50% of Binance spot |
| Quantity sanity | Min quantity | > 0 |
| Row count sanity | Daily row count | > 1000 trades/day |

---

## 8. Reproducibility Procedure

1. Record download date and time
2. Compute SHA-256 hash of each downloaded ZIP
3. Store hash manifest in `data/hist/archives/{SYMBOL}/MANIFEST.json`
4. Normalize to Parquet using same pipeline as BTCUSDT
5. Validate against schema and sanity checks
6. Record validation results in `data/research/V9_DATA_VALIDATION.md`

---

## 9. Pipeline Requirements

| Requirement | Implementation |
|-------------|---------------|
| Deterministic | Same input → same output |
| Restartable | Can resume interrupted downloads |
| Resumable | Skip already-downloaded files |
| Checksummed | SHA-256 verification |
| UTC normalized | All timestamps in UTC |
| Duplicate-safe | agg_trade_id dedup |
| Gap-detected | Daily file presence check |
| Schema validated | Column names and types checked |
| No look-ahead | Raw data preserved, normalized separately |

---

## 10. Download Sequence

1. ETHUSDT (highest liquidity, most important)
2. SOLUSDT
3. BNBUSDT
4. XRPUSDT
5. ADAUSDT
6. AVAXUSDT
7. DOTUSDT
8. LINKUSDT
9. MATICUSDT
10. DOGEUSDT

**Start with 90-day minimum viable sample.** If V9 passes initial tests, extend to 730 days.

---

## 11. Fallback Options

| Option | Source | Limitation |
|--------|--------|------------|
| Binance Vision | data.binance.vision | Primary source, no API key needed |
| Binance REST API | /fapi/v1/aggTrades | Rate-limited, max 1000 trades/request |
| CCXT | ccxt library | Wrapper around Binance API |
| Third-party | Kaiko, TickSuite | Paid, not free |

---

*Specification frozen: 2026-08-31*
*Implementation authorization: PENDING pipeline build*
