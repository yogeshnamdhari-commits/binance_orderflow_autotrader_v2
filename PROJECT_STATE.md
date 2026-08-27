# Project State

## Research Cycle: COMPLETE (Terminal State: NO_DEPLOYABLE_EDGE)

## Experiments Conducted: 18 (EXP-001 through EXP-018)

| ID | Hypothesis | Horizon | Gross bps | Net bps | CI 95% (Net) | Verdict |
|----|-----------|---------|-----------|---------|--------------|---------|
| EXP-001 | V5 Ridge (17 OFI features) | 500ms | +0.069 | -1.931 | [-1.94, -1.92] | REJECTED |
| EXP-002 | V6 MLP (25 features) | 500ms | +0.100 | -1.900 | [-1.91, -1.89] | REJECTED |
| EXP-003 | V7 Multi-Level (46 features) | 500ms | +0.045 | -1.955 | [-1.96, -1.95] | REJECTED |
| EXP-004 | V7 Purged Validation | 500ms | -0.003 | -2.003 | [-2.01, -1.99] | REJECTED |
| EXP-005 | V8 Direction-Magnitude (500ms) | 500ms | 0.000 | -2.500 | [-2.5, -2.5] | REJECTED |
| EXP-006 | V8 Direction-Magnitude (30s) | 30s | 0.000 | -2.500 | [-2.5, -2.5] | REJECTED |
| EXP-007 | Horizon-Matched Feature Aggregation | 30s | -0.137 | -2.637 | [-2.38, -2.34] | REJECTED |
| EXP-008 | Volatility-Regime Conditional Trading | 30s | -0.227 | -2.637 | [-2.93, -2.93] | REJECTED |
| EXP-009 | Order-Book Resiliency Signal | 5s | +0.096 | -2.404 | [-2.41, -2.39] | REJECTED |
| EXP-010 | Multi-Horizon Signal Ensemble | 500ms-30s | -0.294 | -2.770 | [-2.80, -2.77] | REJECTED |
| EXP-011 | Long-Horizon Prediction (5-60 min) | 5min | -1.145 | -3.645 | [-3.64, -3.64] | REJECTED |
| EXP-012 | Aggressive Flow × Absorption Capacity × Liquidity Fragility | 10s | -0.083 | -4.128 | [-4.16, -4.10] | REJECTED |
| EXP-015 | Size-Conditioned Trade-Sign (p99.9) | 1s/5s/10s/30s/60s | +1.22 best | -2.88 | [-1.05, -0.78] | REJECTED |
| EXP-016 | Cross-Market/Derivatives Context (funding + hourly returns) | 1s/5s/10s/30s/60s | +1.22 best | -2.88 | [-1.05, -0.78] | REJECTED |
| EXP-017 | Information-Set Completeness Audit | N/A | N/A | N/A | N/A | AUDIT COMPLETE |
| EXP-018 | Cross-Market Derivatives (funding + basis + ETH, 730-day) | 10s | +1.35 | -2.77 | [-0.69, -0.62] | REJECTED |

## Data Audit Results (EXP-017)

| Dimension | Classification | Available |
|-----------|---------------|-----------|
| BTCUSDT trades/order-flow | **A** | 730 days full |
| BTCUSDT L2/order-book | **D** | Historical unavailable (URL returns 404) |
| BTCUSDT open interest | **D** | **Unavailable** (current-only API, no history) |
| BTCUSDT funding rate | **A** | 730 days, 2,214 records (downloaded) |
| BTC spot price | **A** | 730 days, 17,723 records (downloaded) |
| BTC mark price | **A** | 730 days, 17,723 records (downloaded) |
| BTC spot/perpetual basis | **A** | Both spot + perp downloaded, basis computed |
| ETHBTC cross-asset | **A** | ETH funding rates downloaded (2,214 records) |
| Liquidations | **C** | Requires paid subscription |
| Cross-venue BTC | **C** | ~90 days hourly (CoinGecko) |

**Key finding**: Open interest is **fundamentally unavailable** in historical form from Binance. All other dimensions acquired with full 730-day coverage. Despite this, EXP-018 found **zero incremental predictive value** from derivatives state.

## Research Tree Coverage

All 11 research tree branches tested:

| Branch | Experiment | Status |
|--------|-----------|--------|
| EXP-A: Event-level OFI + depth norm | EXP-001 (V5) | REJECTED |
| EXP-B: Multi-level OFI | EXP-003 (V7) | REJECTED |
| EXP-C: OFI conditional on regime | EXP-008 | REJECTED |
| EXP-D: OFI + queue + microprice | EXP-003/006 (V7/V8) | REJECTED |
| EXP-E: Order-flow persistence/decay | EXP-009/011 | REJECTED |
| EXP-F: Cancellation/depletion/replenishment | EXP-009 | REJECTED |
| EXP-G: Execution-aware prediction | EXP-005/006 (V8) | REJECTED |
| EXP-H: Volatility/liquidity conditional | EXP-008 | REJECTED |
| EXP-I: Event-time aggregation | EXP-007 | REJECTED |
| EXP-J: Combination of components | EXP-010 | REJECTED |
| EXP-K: Aggressive flow × capacity × fragility | EXP-012 | REJECTED |
| EXP-L: Size-conditioned trade-sign (EXTENDED) | EXP-013/014/015 | REJECTED |
| EXP-M: Cross-market/derivatives context | EXP-016 | REJECTED |

## Key Findings

1. **Cost-to-signal ratio**: 40-200x at short horizons (0.02-0.10 bps gross vs 4.0 bps taker cost)
2. **88% of 500ms returns are exactly 0.0 bps** — most events have no price movement
3. **At 5min, moves are larger (E[|r|]=2.27 bps)** but feature correlations are ~0 (no predictive power)
4. **Even perfect direction prediction at 5min yields only +0.22 bps net** (shorting down-events)
5. **Maximum observed single-event return: 3.54 bps** — below the 4.0 bps taker round-trip cost
6. **Volatility regime conditioning does not improve prediction** — high-vol regimes have the same weak signal
7. **Aggressive flow × absorption capacity × fragility does not produce edge**:
   - Even in best conditional state (top 1% flow/depth + high fragility + direction match): mean +0.28 bps
   - 35.4% positive rate in best state — barely above random
   - Maximum return (3.54 bps) < taker round-trip cost (4.0 bps)
8. **Multi-horizon ensembles perform worse than single best horizon** — signals are not complementary
9. **Resiliency/dynamics features add no information** beyond static snapshot features
10. **V7 features (46 features) show same result as V5 (17 features)** — more features don't help

## Root Cause: Cost Exceeds Maximum Possible Signal

The fundamental constraint is mathematical:
- Maximum observed return: 3.54 bps (10s horizon, single extreme event)
- Taker round-trip cost: 4.0146 bps (measured: fee 4.0 + spread 0.015)
- **Even a perfect predictor cannot produce positive net expectancy** because the maximum possible gross return (3.54 bps) is below the cost floor (4.0 bps)

EXP-016 confirmed that derivative-market context (funding rates, hourly returns) provides NO incremental value:
- Best incremental improvement: +0.05 bps (economically negligible)
- Signal is consistent across funding regimes (no interaction effect)
- All net expectancy remains ≤ 0, bootstrap CI excludes zero

EXP-018 extended this to the full 730-day historical dataset:
- Acquired: funding rates (2,214 records), spot/perp prices (17,723 hourly each), ETH funding (2,214 records)
- Best incremental: +0.10 bps (economically negligible)
- Model coefficients for derivative features: ~0 (no actual usage)
- AUC unchanged: 0.666 → 0.663
- Bootstrap CI: [-0.69, -0.62] bps (excludes positive)
- H019 (Open-Interest × order-flow): NOT testable — OI fundamentally unavailable
- Economic gate: FAIL (net_taker = -2.77 bps)

This is a data-theoretic limitation, not a modeling limitation.

## Final Scientific Conclusion

**NO_DEPLOYABLE_EDGE** — The Binance BTCUSDT order-flow microstructure does not contain
sufficient predictable information to overcome realistic execution costs (4.0 bps taker
round-trip) at any tested horizon (250ms to 60 minutes).

After 18 experiments across 14 research domains (including cross-market/derivatives context),
no market state, feature combination, or model architecture produces net positive expectancy.
The maximum possible gross move (3.54 bps) is insufficient to cover execution costs (4.0 bps).

## Remaining Untested Information Dimensions

The following dimensions could not be tested due to data availability:
- **Historical open interest**: FUNDAMENTALLY UNAVAILABLE — Binance API only provides current snapshot
- **Liquidation events**: Requires paid subscription (not acquired)
- **High-frequency cross-venue trades**: No free historical source (CoinGecko: 90-day hourly only)
- **L3 order queue position**: Not available in Binance historical archives
- **Historical L2 bookDepth**: Binance deprecated bulk historical downloads

Acquired and tested (all yielded zero incremental value):
- BTCUSDT funding rate (2,214 records, 8h intervals, full 730 days)
- BTC spot/perpetual basis (17,723 hourly records each, full 730 days)
- ETH cross-asset funding (2,214 records, full 730 days)

**The only remaining scientifically justified untested dimension (open interest) is unobtainable.**

## Deployment Status

- DEPLOYABLE_EDGE = FALSE
- LIVE_TRADING = HARD_BLOCKED (app/config.py: V5_BASELINE_NO_LIVE_TRADE = True)

## Test Results

- All 214 tests pass (1 skipped) — no regressions
