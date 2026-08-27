# V5 Baseline — Frozen

## Model
- **Type**: Closed-form Ridge Regression (L2 regularized OLS)
- **Alpha**: 0.05
- **Features**: 17 order-flow features (OFI/MLOFI + depth imbalance)
- **Training**: Single chronological pass on 70% earliest timestamps
- **Horizon**: 500 ms forward mid-price return (bps)
- **Status**: FROZEN — coefficients saved to `data/research/v5_model.json`

## Features
ofi_l1, ofi_norm_l1, qi_l1, di_l5, di_l10, mpd_bps, spread_bps, bid_cancel_bps,
ask_add_bps, cancel_pressure, tfi_500, liq_depletion, log_depth1, log_depth5,
log_event_rate, depth_slope_bps, vol_500

## Dataset
- **Source**: Binance BTCUSDT futures L2 depth @100ms + aggTrades
- **Sessions**: 20260818-194920, 20260818-195221
- **Total rows**: ~23,981 events
- **Split**: 70/15/15 chronological (train/validation/OOS)
- **OOS rows**: 3,876

## Economic Validation Results
| Metric | Value | 95% CI |
|--------|-------|--------|
| OOS Samples | 3,876 | — |
| Gross Expectancy | +0.069 bps | [+0.057, +0.081] bps |
| Maker Fee | 2.0 bps | — |
| Net Expectancy | **-1.93 bps** | **[-1.94, -1.92] bps** |
| % Above Maker Gate (2 bps) | 0.00% | — |
| **Verdict** | **NEGATIVE_EDGE** | — |

## Root Cause
The gross signal is statistically positive but economically insignificant (< 0.1 bps).
The 2.0 bps maker fee completely consumes the signal. Zero observations exceed the
execution gate. The hypothesis (OFI/MLOFI features at 500ms horizon) lacks executable edge.

## Rejection Date
2026-08-22

## Do Not
- Tune V5 parameters
- Retrain V5 on new data
- Optimize V5 thresholds
- Use V5 as a production signal
