# DATA INVENTORY — ACTUAL LOCAL FILESYSTEM

**Date:** 2026-08-31
**Source:** Direct filesystem inspection (not GitHub tracked files)
**Repository:** `/Users/targetmobile/Downloads/binance_orderflow_autotrader_v2`

---

## 1. BTCUSDT TRADE DATA (AGGTRADES)

| Property | Value |
|----------|-------|
| Status | **AVAILABLE** |
| Location | `data/hist/normalized/BTCUSDT/aggTrades/` |
| Format | Parquet (one file per day) |
| File count | 730 |
| Date range | 2024-08-16 to 2026-08-15 |
| Total size | 21.13 GB |
| Schema | `agg_trade_id, price, quantity, first_trade_id, last_trade_id, transact_time, is_buyer_maker` |
| Avg trades/day | ~500,000 - 1,400,000 |
| Duplicates | 0 (verified on sample) |
| Timestamp resolution | Millisecond |
| Timezone | UTC (unix ms) |

**Archives:** 730 ZIP files, 13.81 GB (SHA256-verified)

**Raw CSV:** 6 files (2024-09-06 to 2024-09-14 only), 384 MB

---

## 2. BTCUSDT FUNDING RATES

| Property | Value |
|----------|-------|
| Status | **AVAILABLE** |
| Location | `data/hist/derivatives/BTCUSDT/funding_rates_730d.parquet` |
| Records | 2,214 |
| Date range | 730 days (8-hour intervals) |
| Schema | `symbol, fundingTime, fundingRate, markPrice, rateType` |

---

## 3. ETH FUNDING RATES

| Property | Value |
|----------|-------|
| Status | **AVAILABLE** |
| Location | `data/hist/derivatives/BTCUSDT/eth_funding_rates_730d.parquet` |
| Records | 2,214 |
| Schema | `symbol, fundingTime, fundingRate, markPrice, rateType` |

---

## 4. BTC HOURLY PRICES (SPOT + PERP)

| Property | Value |
|----------|-------|
| Status | **AVAILABLE** |
| Location | `data/hist/derivatives/BTCUSDT/spot_hourly_730d.parquet`, `perp_hourly_730d.parquet` |
| Records | 17,723 each |
| Schema | `open_time, open, high, low, close, volume, close_time, quote_asset_volume, num_trades, taker_buy_base, taker_buy_quote, ignore, ts_ms` |

---

## 5. LIVE SESSION DATA

| Property | Value |
|----------|-------|
| Status | **AVAILABLE** |
| Location | `data/live/v2/` through `data/live/v5/` |
| Sessions | 27 (v2), 12 (v3), 12 (v4), 27 (v5) |
| Format | JSONL (raw.jsonl, derived.jsonl, session.json) |
| Content | L2 depth snapshots + deltas, trades |
| Depth format | `[price, qty]` arrays (NO order IDs) |
| Timestamp | UTC milliseconds |

---

## 6. EXP018 CROSS-MARKET FEATURES

| Property | Value |
|----------|-------|
| Status | **AVAILABLE** (limited) |
| Location | `data/hist/derivatives/BTCUSDT/exp018_events.parquet` |
| Records | 901,859 |
| Schema | `transact_time, side, ret_10s_bps, f_sign, f_abs, basis_bps, spot_ret_1h, perp_ret_1h, eth_f_sign, eth_f_abs` |
| Note | Derived features, NOT raw altcoin trades |

---

## 7. ALTCOIN TRADE DATA

| Property | Value |
|----------|-------|
| Status | **UNAVAILABLE** |
| ETHUSDT aggTrades | NOT FOUND |
| SOLUSDT aggTrades | NOT FOUND |
| BNBUSDT aggTrades | NOT FOUND |
| XRPUSDT aggTrades | NOT FOUND |
| DOGEUSDT aggTrades | NOT FOUND |
| ADAUSDT aggTrades | NOT FOUND |
| AVAXUSDT aggTrades | NOT FOUND |
| LINKUSDT aggTrades | NOT FOUND |
| DOTUSDT aggTrades | NOT FOUND |
| MATICUSDT aggTrades | NOT FOUND |

**Confirmed:** Zero altcoin trade files exist anywhere in `data/`.

---

## 8. HISTORICAL L2 ORDER BOOK

| Property | Value |
|----------|-------|
| Status | **UNAVAILABLE** |
| Note | Binance does not publish historical L2 order book data. Only available via live WebSocket. |

---

## 9. OPEN INTEREST

| Property | Value |
|----------|-------|
| Status | **UNAVAILABLE** |
| Note | Binance API only provides current snapshot. No historical endpoint. |

---

## 10. LIQUIDATION DATA

| Property | Value |
|----------|-------|
| Status | **UNAVAILABLE** |
| Note | Requires paid subscription (Binance historical liquidations not freely available). |

---

## V9 HYPOTHESIS TESTABILITY MATRIX

| Feature | Required | Available | Quality | Usable | Reason |
|---------|----------|-----------|---------|--------|--------|
| BTC aggTrades (predictor) | Yes | YES | HIGH | YES | 730 days, full schema |
| BTC funding rate | Yes | YES | HIGH | YES | 2,214 records |
| ETH aggTrades (target) | Yes | **NO** | — | **NO** | Not in local data |
| SOL aggTrades (target) | Yes | **NO** | — | **NO** | Not in local data |
| BNB aggTrades (target) | Yes | **NO** | — | **NO** | Not in local data |
| XRP aggTrades (target) | Yes | **NO** | — | **NO** | Not in local data |
| DOGE aggTrades (target) | Yes | **NO** | — | **NO** | Not in local data |
| ADA aggTrades (target) | Yes | **NO** | — | **NO** | Not in local data |
| AVAX aggTrades (target) | Yes | **NO** | — | **NO** | Not in local data |
| LINK aggTrades (target) | Yes | **NO** | — | **NO** | Not in local data |
| DOT aggTrades (target) | Yes | **NO** | — | **NO** | Not in local data |
| MATIC aggTrades (target) | Yes | **NO** | — | **NO** | Not in local data |

## VERDICT

**V9 FULL TEST = BLOCKED BY DATA AVAILABILITY**

The cross-asset lead-lag hypothesis requires altcoin minute-level trade data that does not exist locally. The BTC predictor side is fully available. The altcoin target side is entirely missing.

---

## DATA QUALITY NOTES

1. **BTC aggTrades schema is complete:** Includes trade IDs, price, quantity, time, and buyer-maker flag
2. **No duplicates detected** in sampled files
3. **Timestamp continuity:** Files are contiguous by date (730 consecutive days)
4. **Trade IDs present:** `agg_trade_id` allows deduplication and ordering verification
5. **is_buyer_maker flag:** Enables signed volume/OFI computation
6. **Live session data:** Confirmed L2-only (no order IDs), consistent with V6 spec limitations

---

*Inventory completed: 2026-08-31*
*Method: Direct filesystem inspection (not inferred from filenames)*
*Integrity: Verified against actual file contents*
