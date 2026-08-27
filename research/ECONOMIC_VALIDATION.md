# Economic Validation Report

## Cost Model

All cost assumptions verified against measured data from `data/live/cost_calibration.json`:

| Component | Value | Source |
|-----------|-------|--------|
| Taker fee (round-trip) | 4.0 bps | Binance fee schedule (0.02% × 2) |
| Maker fee (round-trip) | 2.0 bps | Binance fee schedule (0.01% × 2) |
| Spread (median) | 0.0146 bps | Measured from cost sampler |

## NET_EXPECTANCY = GROSS_EXPECTANCY - Σ COSTS

### EXP-012 Economic Analysis (3-day sample, 2.7M trades)

| Horizon | Directional Profit | Perfect Prediction | Taker Net | Maker Net |
|---------|-------------------|-------------------|-----------|-----------|
| 10s | 0.43 bps | 2.92 bps | -3.58 bps | -1.57 bps |
| 30s | 0.42 bps | 4.60 bps | -3.59 bps | -1.59 bps |
| 60s | 0.41 bps | 6.73 bps | -3.61 bps | -1.61 bps |
| 5min | 0.46 bps | 15.38 bps | -3.55 bps | -1.54 bps |

### EXP-013 Economic Analysis (Two-Stage Event + Direction)

**Key insight**: At 5min horizon, 80.6% of trades see |return| > 4.0 bps cost.
If we could perfectly predict both event AND direction, net = +11.77 bps/trade.

But the achievable accuracy is far below the required threshold:

| Component | Required | Achieved | Gap |
|-----------|----------|----------|-----|
| Event prediction (5min) | AUC > 0.8 | AUC = 0.505 | -0.295 |
| Direction prediction (book features) | 63.5% (taker) | 52.4% | -11.1 pp |
| Direction prediction (maker cost) | 56.7% | 52.4% | -4.3 pp |

### Signal Strength Degradation Across Horizons

| Horizon | E[|ret|] | IC (trade-sign) | AUC | Required Acc (taker) | Achieved Acc |
|---------|---------|-----------------|-----|---------------------|--------------|
| 5s | 2.38 | 0.123 | 0.562 | 118.7% (impossible) | ~56% |
| 10s | 3.20 | 0.083 | 0.533 | 112.7% (impossible) | ~54% |
| 30s | 5.35 | 0.055 | 0.522 | 87.5% | ~53% |
| 60s | 7.38 | 0.045 | 0.518 | 77.2% | ~52% |
| 5min | 15.38 | 0.012 | 0.506 | 63.1% | ~51% |
| 15min | 23.98 | 0.010 | 0.505 | 58.4% | ~51% |

### Bootstrap Confidence Intervals (95%, 2000 resamples, seed=42)

EXP-013 two-stage model (5min, maker cost):
- Net mean: -1.60 bps
- CI95: [-1.62, -1.58]
- 0% positive

No confidence interval crosses zero at any horizon.
