# V6 Baseline — Frozen

## Model
- **Type**: MLPRegressor (scikit-learn)
- **Architecture**: 2 hidden layers (32, 16 units), ReLU, dropout=0.1, L2=1e-4
- **Features**: 17 V5 base + 8 interaction features = 25 features
- **Training**: Chronological 70/15/15 split, early stopping
- **Horizon**: 500 ms forward mid-price return (bps)
- **Status**: FROZEN — model saved to `data/research/v6_model/v6_model.joblib`

## Features
Base (17): ofi_l1, ofi_norm_l1, qi_l1, di_l5, di_l10, mpd_bps, spread_bps,
bid_cancel_bps, ask_add_bps, cancel_pressure, tfi_500, liq_depletion,
log_depth1, log_depth5, log_event_rate, depth_slope_bps, vol_500

Interactions (8): ofi_x_depth1, ofi_x_vol500, imbalance5_x_spread, ofi_x_qi,
tfi500_x_liqdep, ofi_x_tfi500, di5_x_spread, vol500_x_spread

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
| Gross Expectancy | +0.0999 bps | [+0.088, +0.111] bps |
| Maker Fee | 2.0 bps | — |
| Net Expectancy | **-1.90 bps** | **[-1.91, -1.89] bps** |
| % Above Maker Gate (2 bps) | 0.00% | — |
| **Verdict** | **NEGATIVE_EDGE** | — |

## Root Cause
Same as V5: gross signal statistically positive but economically insignificant.
The nonlinear MLP with interaction features did not extract additional executable
edge beyond the linear ridge. The 2.0 bps maker fee dominates.

## Rejection Date
2026-08-22

## Do Not
- Tune V6 hyperparameters
- Add more hidden layers/units
- Retrain V6 on new data
- Use V6 as a production signal
