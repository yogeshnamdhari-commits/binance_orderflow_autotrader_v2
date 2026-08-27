# EXP-017: Information-Set Completeness and Data Acquisition Audit

## Objective

Determine whether the signal-to-cost gap identified across EXP-001 through
EXP-016 can be investigated using synchronized historical derivative,
cross-market, and liquidation data that currently exists but was not
acquired.

This experiment performs a **data-availability audit first**. No modeling
is conducted until the usable information set is established.

## Audit Results Summary

| Dimension | Classification | Available Data |
|-----------|----------------|----------------|
| 1. BTCUSDT trades/order-flow | **A** | 730 days (full) |
| 2. BTCUSDT L2/order-book | **B** | 21 sessions, 1 day only |
| 3. BTCUSDT open interest | **D** | Unavailable (current-only API) |
| 4. BTCUSDT funding rate | **B** | 30 days downloaded, full 730 available via API |
| 5. BTC spot price | **B** | 30 days downloaded, full range available |
| 6. BTC perpetual mark price | **B** | Available via API (500 records) |
| 7. BTC spot/perpetual basis | **B** | Both endpoints available, not combined |
| 8. ETHBTC cross-asset | **B** | ETHUSDT data available, not downloaded |
| 9. Liquidation events | **C** | Requires paid subscription (Coinalyze/CoinGlass) |
| 10. Cross-venue BTC prices | **C** | Limited historical (CoinGecko ~90 days hourly) |

### Classification Key
- **A = sufficient historical data** — full 730-day coverage with millisecond precision
- **B = partial historical data** — data available but requires download; overlapping period < 730 days
- **C = current-only** — real-time APIs exist; limited/no historical data
- **D = unavailable** — no historical data source found

## Key Findings

### 1. Open Interest (Classification: D — UNAVAILABLE)

**Binance does not provide historical open interest data.**

- API endpoint `/fapi/v1/openInterest` returns only the **current** snapshot
- No historical OI endpoint exists in the Binance Futures REST API
- The data.binance.vision bulk download does **not** include `openInterest` type
- **Confirmed**: OI was unavailable for EXP-016 and remains unavailable.
- Using current OI for historical events would constitute future leakage.

This was the dimension most expected to provide incremental value. Its
absence is a hard constraint.

### 2. Funding Rate (Classification: B — PARTIAL)

- Available via `/fapi/v1/fundingRate` (8-hour intervals)
- Each call returns max 1000 records (~33 days at 8h intervals)
- Full 730-day history requires ~22 API calls with pagination
- Currently only 30 days downloaded (91 records)
- **Reconstructable**: YES

### 3. Spot/Perpetual Basis (Classification: B — PARTIAL)

- Spot klines: Available but URL format changed (404 on bulk downloads)
- Perp klines: Available via API, 500 records max per call
- Mark price: Available via API (`/fapi/v1/klines` with `markPrice`)
- **Reconstructable**: YES via API pagination

### 4. Liquidations (Classification: C — CURRENT-ONLY/PAID)

- Binance does not provide historical liquidation data
- No free source exists
- Coinalyze and CoinGlass offer paid subscriptions
- **Reconstructable**: Only with paid subscription ($50-200/month)

### 5. Cross-Venue (Classification: C — CURRENT-ONLY)

- CoinGecko: 90-day hourly BTC/USD (free, rate-limited)
- Coinbase/Kraken: Real-time APIs only, no free historical tick data
- **Reconstructable**: Partially (CoinGecko), not at trade-level granularity

### 6. ETH Cross-Asset (Classification: B — PARTIAL)

- ETHUSDT funding rate, perp trades, and klines all available via API
- Would require downloading ~730 days of ETH data
- **Reconstructable**: YES

## Overlapped Usable Period

| Combination | Overlap Period | Usable Sample Size |
|-------------|----------------|-------------------|
| Trade + Funding | 730 days | 730 days (once funding downloaded) |
| Trade + Hourly price | 730 days | 730 days (once spot/klines downloaded) |
| Trade + Basis | 730 days | 730 days (once both spot+perp downloaded) |
| Trade + ETH | 730 days | 730 days (once ETH data downloaded) |
| Trade + OI | 0 days | **None — OI unavailable** |
| Trade + Liquidations | 0 days | **None — requires paid subscription** |
| Trade + Cross-venue | ~90 days | ~90 days (CoinGecko hourly only) |

## Data That Was Actually Used in EXP-016

EXP-016 only used 30 days of funding rates and hourly prices. The full
730-day overlap is now confirmed to be available (pending download).

## Next Steps

1. **Download the full 730 days of funding rates** (requires API pagination)
2. **Download 730 days of hourly spot and perp klines** for basis calculation
3. **Download ETHUSDT data** for cross-asset state
4. **Construct basis, funding, hourly return, and cross-asset features**
5. **Test incremental value** against the EXP-015 baseline using:
   - Walk-forward validation
   - Purged splits
   - Bootstrap confidence intervals
   - Economic gate (4.0146 bps taker cost)

## Dimensions That CANNOT Be Obtained

| Dimension | Reason |
|-----------|--------|
| Historical open interest | No API or archive provides this |
| Liquidation events | Requires paid subscription |
| High-frequency cross-venue trades | No free historical source |
| L3 order queue depth | Not available in Binance historical data |

## Scientifically Justified Experiment Design (Pending Data Download)

### A. Baseline
EXP-015 size-conditioned trade-sign (p99.9, 10s horizon)
- IC = 0.17, dp = 1.13 bps, net(maker) = -0.87 bps

### B. + Funding Rate
Add causal funding rate and sign as features
- Test: does funding regime condition the trade-sign signal?

### C. + Basis
Add spot-perpetual basis as a feature
- Test: does basis level predict order-flow persistence?

### D. + Cross-Asset (ETH)
Add ETH/USD return and ETH funding rate as features
- Test: does ETH momentum or funding predict BTC order-flow impact?

### E. Combined (only if individual branches show incremental value)
Logistic regression combining trade-sign + derivative context

### Evaluation
- Chronological 70/30 train/test split
- All features strictly lagged (no future data)
- Bootstrap 95% CI on net-maker expectancy
- Economic gate: NET_TAKER > 0 AND NET_MAKER > 0
- Walk-forward stability across 5 windows

## Conclusion

Three dimensions have **sufficient data for testing**:
1. Funding rate (full 730 days available via API)
2. Spot/perpetual basis (both endpoints available)
3. Cross-asset ETH state (ETH data available)

Two dimensions are **unavailable**:
1. Open interest — no historical source exists
2. Liquidations — requires paid subscription

The audit is complete. The next step is to download the full historical
data for the available dimensions and run the incremental information test.
**Do not proceed to EXP-018 until this data is acquired and tested.**
