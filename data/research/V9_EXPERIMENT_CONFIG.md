# V9 Experiment Configuration — FROZEN

**Date:** 2026-08-31
**Status:** FROZEN — do not modify after seeing OOS results

---

## Hypothesis
H1: BTC lagged returns predict altcoin returns at 5-15 min horizons, generating positive net expectancy after costs.

## Target
Altcoin 5-minute forward log return: target[c,t] = ln(close[c, t+5] / close[c, t]) in bps

## Predictors (pre-registered)
1. btc_ret_1m: BTC lagged 1-min return
2. btc_ret_5m: BTC lagged 5-min return
3. btc_ret_10m: BTC lagged 10-min return
4. ofi_5m: BTC signed OFI (5-min trailing)
5. realized_vol_5m: BTC realized volatility (5-min trailing)
6. funding_rate: BTC funding rate (pro-rated)

## Horizons
[5, 10, 15] minutes

## Rebalancing Frequencies
[5, 10, 13, 15] minutes

## Universe
ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, ADAUSDT, AVAXUSDT, DOTUSDT, LINKUSDT, POLUSDT, DOGEUSDT

## Walk-Forward Structure
| Parameter | Value | Deviation Note |
|-----------|-------|----------------|
| Training window | 30 days | Reduced from 60 due to 92-day data limit |
| Validation window | 10 days | Per spec |
| OOS window | 10 days | Per spec |
| Step | 10 days | Per spec |
| Minimum folds | 5 | Per spec |

**Deviation justification:** Spec assumes 730 days. Only 92 days available. 30-day training enables 5 folds covering 50 OOS days (meets spec minimum).

## Model
Ridge regression (α=0.05, closed-form, same family as V5)

## Cost Model
| Component | Value |
|-----------|-------|
| Exchange taker fee | 10.0 bps round-trip |
| Spread | 0.016 bps |
| Slippage | 0.008 bps |
| Market impact | 0.1 bps |
| Adverse selection | 0.5 bps |
| Latency | 0.05 bps |
| **Total per-coin per-side** | **~10.57 bps** |
| **Portfolio per rebalance** | **~85 bps (base)** |

## Statistical Tests
| Test | Criterion |
|------|-----------|
| Primary endpoint | Net > 0, CI excludes zero, t > 3.0 |
| Consistency | Positive in ≥ 60% of folds |
| Cost sensitivity | Net > 0 at 2× costs |
| Permutation control | Return > 95th percentile of null |

## Multiple Testing
Bonferroni across 12 tests (3 horizons × 4 frequencies), α = 0.00417

## Falsification
ANY of: Net ≤ 0, CI includes zero, t ≤ 3.0, < 60% folds positive, Net ≤ 0 at 2× costs, return ≤ 95th percentile null

## Random Seed
42

---
*Configuration frozen: 2026-08-31*
