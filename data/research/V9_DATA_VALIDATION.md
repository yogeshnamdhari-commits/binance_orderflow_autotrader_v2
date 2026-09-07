# V9 Data Acquisition & Validation Report

**Date:** 2026-08-31
**Status:** COMPLETE — DATA ACQUIRED AND VALIDATED

---

## 1. Acquisition Summary

| Symbol | Files | Rows | Size (MB) | Date Range | Status |
|--------|-------|------|-----------|------------|--------|
| ETHUSDT | 92 | 109,006,567 | 1,892 | 2026-05-31 to 2026-08-30 | PASS |
| SOLUSDT | 92 | 23,130,076 | 403 | 2026-05-31 to 2026-08-30 | PASS |
| BNBUSDT | 92 | 24,324,249 | 424 | 2026-05-31 to 2026-08-30 | PASS |
| XRPUSDT | 92 | 19,889,901 | 347 | 2026-05-31 to 2026-08-30 | PASS |
| ADAUSDT | 92 | 8,486,979 | 148 | 2026-05-31 to 2026-08-30 | PASS |
| AVAXUSDT | 92 | 9,463,159 | 165 | 2026-05-31 to 2026-08-30 | PASS |
| DOTUSDT | 92 | 5,425,894 | 95 | 2026-05-31 to 2026-08-30 | PASS |
| LINKUSDT | 92 | 7,894,403 | 138 | 2026-05-31 to 2026-08-30 | PASS |
| POLUSDT | 92 | 5,729,298 | 100 | 2026-05-31 to 2026-08-30 | PASS |
| DOGEUSDT | 92 | 13,215,098 | 230 | 2026-05-31 to 2026-08-30 | PASS |
| **Total** | **920** | **226,565,624** | **~5.1 GB** | **92 days** | **ALL PASS** |

---

## 2. Validation Results

| Check | Result |
|-------|--------|
| Schema correctness | PASS — all files have correct 7-column schema |
| Duplicate trades | PASS — 0 duplicates (by agg_trade_id) |
| Header contamination | PASS — 0 header rows in data |
| Timestamp monotonicity | PASS — all files monotonically increasing |
| Large gaps (>1 hour) | PASS — 0 gaps detected |
| UTC alignment | PASS — all timestamps in UTC milliseconds |
| Date coverage | PASS — 92 consecutive days for all symbols |
| Price sanity | PASS — all prices within expected ranges |

---

## 3. Deviations from Specification

| Deviation | Reason | Impact |
|-----------|--------|--------|
| MATICUSDT → POLUSDT | Binance renamed MATIC to POL | None — same asset, new ticker |

---

## 4. Pipeline Fixes Applied

| Bug | Fix |
|-----|-----|
| CSV header row treated as data | Added `skiprows=1` to `pd.read_csv()` |
| Mixed-type columns | Added explicit `pd.to_numeric()` with `errors='coerce'` |
| Header contamination in dedup | Added `dropna()` after numeric coercion |

---

## 5. Storage Location

| Type | Location |
|------|----------|
| Raw archives | `data/hist/archives/{SYMBOL}/aggTrades/` (ZIP files) |
| Normalized data | `data/hist/normalized/{SYMBOL}/aggTrades/` (Parquet) |
| Validation results | `data/research/v9_validation_results.json` |
| Download manifest | `data/hist/archives/v9_download_manifest.json` |

---

## 6. V9 OOS Test Status

**STATUS: UNBLOCKED**

The acquired dataset satisfies the V9 research specification requirements:
- 10 altcoin symbols (MATIC→POL rename noted)
- 92 days of minute-level trade data (exceeds 90-day minimum)
- All data validated for integrity
- BTC predictor data already available (730 days)

The V9 cross-asset lead-lag OOS experiment can now proceed.

---

*Report generated: 2026-08-31*
*Acquisition pipeline: app/v9_data_pipeline.py*
*Validation: automated + manual inspection*
