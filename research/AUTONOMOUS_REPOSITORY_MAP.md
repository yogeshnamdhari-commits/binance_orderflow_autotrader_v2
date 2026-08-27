# Autonomous Repository Map

## Data Sources

### 1. V4 Session Data (High-Frequency L2 Events)
- **Path**: `data/live/v4/*/derived_v4.jsonl`
- **Sessions**: 12 (all from 2026-08-18, 5-minute windows: 19:07-19:52 UTC)
- **Event Types**: `depth` (19,359), `trade` (6,563)
- **Sampling Frequency**: Event-driven (no fixed interval; depth events at ~10ms intervals during active periods)
- **Order Book Depth**: Full level snapshots in `levels_bid` / `levels_ask` arrays (variable depth, typically 10-20 levels)
- **Fields per event**:
  - `ts_ms`, `recv_ms`, `seq`, `kind`
  - `best_bid`, `best_ask`, `mid`, `spread_bps`, `microb_price`, `mpd_bps`
  - `qi_l1`, `di_l5`, `di_l10`, `depth_slope_bps`
  - `ofi_l1`, `ofi_norm_l1`, `mlofi_weighted`, `ofi_decay`
  - `bid_add_bps`, `bid_cancel_bps`, `ask_add_bps`, `ask_cancel_bps`, `cancel_pressure`
  - `log_depth1`, `log_depth5`, `log_event_rate`
  - `tfi_500`, `signed_vol_500`, `trade_rate`, `liq_depletion`
  - `trade_price`, `trade_qty`, `trade_maker` (trade events only)
  - `levels_bid`, `levels_ask` (full level arrays)
- **Limitations**: Only 12 sessions, 5-minute windows each, low-volatility period

### 2. Normalized AggTrades Data (730 Days of Trades)
- **Path**: `data/hist/normalized/BTCUSDT/aggTrades/*.parquet`
- **Date Range**: 2024-08-16 to 2026-08-15 (730 days)
- **Fields**: `agg_trade_id`, `price`, `quantity`, `first_trade_id`, `last_trade_id`, `transact_time`, `is_buyer_maker`
- **Trade Volume**: ~2.7M-1.5M trades per day
- **Price Range**: $57,062 (2024) to $117,857 (2025) to $63,170 (2026)
- **Sampling Frequency**: Event-driven (aggregated trades)
- **Limitations**: Aggregated trades only (no order book snapshots), no depth data, no maker/taker distinction at event level

### 3. Cost Calibration Data
- **Path**: `data/live/cost_calibration.json`
- **Measured**: Taker round-trip = 4.0146 bps, Maker fee = 2.0 bps, Spread median = 0.0146 bps
- **Source**: Cost sampler execution data

### 4. Paper Trading / Simulation Data
- **Path**: `data/paper_simulation/`, `data/paper_validation/`
- **Purpose**: Post-deployment validation (not yet used)

## Missing Information

| Data Type | Status | Impact |
|-----------|--------|--------|
| Order book depth (historical) | Only in 12 V4 sessions | Cannot compute book-state features on 730-day data |
| Full L2 stream (all levels) | Only top 10 levels in V4 | Cannot compute deep book dynamics |
| Funding rates | Not available | Cannot compute funding carry |
| Open interest | Not available | Cannot compute OI-driven signals |
| Liquidations | Not available | Cannot compute liquidation cascade signals |
| Cross-exchange data | Only Binance | Cannot compute cross-venue arbitrage |
| Latency measurements | Estimated only | Cannot optimize execution timing |
| Queue position (L3) | Not available | Cannot compute fill probability models |

## Leakage Risks

1. **Timestamp alignment**: V4 derived data uses `ts_ms` (event time), but `recv_ms` is present — must use `ts_ms` for causality
2. **Order book reconstruction**: V4 events include `levels_bid/ask` but these are snapshot states, not incremental — careful when computing OFI
3. **Label overlap**: Forward returns at 10s+ may overlap across consecutive events
4. **Look-ahead in volatility**: Rolling volatility windows must use only past data

## Available Periods

| Data Source | Period | Duration | Events |
|-------------|--------|----------|--------|
| V4 sessions | 2026-08-18 19:07-19:52 UTC | ~45 min | 25,922 |
| AggTrades | 2024-08-16 to 2026-08-15 | 730 days | ~2.2B |
| Cost calibration | 2026-08-17 | 1 session | 1,765 samples |
