# V5 Calibration Report

**Generated at**: 2026-08-22T11:39:01.120760

## Raw V5 Prediction Distribution (OOS set)
- **mean**: 0.0699 bps
- **std**: 0.1964 bps
- **min**: -0.6495 bps
- **max**: 0.6967 bps
- **q05**: -0.3411 bps
- **q25**: -0.0223 bps
- **q50**: 0.1052 bps
- **q75**: 0.2087 bps
- **q95**: 0.2918 bps

## Forward-Return Target Definition
- Horizon: 500 ms
- Definition: r_h = (mid_{t+h} - mid_t) / mid_t * 1e4

## Calibration Method
- Method: binned calibration
- Number of bins: 15
- Bin type: equal-width

## Data Splits
### Train set
- Timestamp range: 1787080068417 to 1787082331201
- Rows: 18145

### Validation set
- Timestamp range: 1787082331303 to 1787082620783
- Rows: 3888

### Oos set
- Timestamp range: 1787082620885 to 1787082921993
- Rows: 3889

## Score Bins
- Bin edges: [-1.0261000695150972, -0.6975073867405899, -0.3689147039660826, -0.04032202119157535, 0.288270661582932, 0.6168633443574394, 0.9454560271319465, 1.2740487099064541, 1.6026413926809613, 1.9312340754554684, 2.259826758229976, 2.588419441004483, 2.9170121237789903, 3.245604806553498, 3.5741974893280055, 3.9027901721025122]
- Bin width: 0.328593
- Bin indices for OOS set (first 10): 3, 2, 2, 3, 3, 3, 3, 3, 3, 3

## Observation Count per Bin
- Bin 0: 42
- Bin 1: 197
- Bin 2: 857
- Bin 3: 2656
- Bin 4: 131
- Bin 5: 4
- Bin 6: 0
- Bin 7: 0
- Bin 8: 0
- Bin 9: 0
- Bin 10: 0
- Bin 11: 0
- Bin 12: 0
- Bin 13: 0
- Bin 14: 1

## Mean Realized Forward Return per Bin (Calibration Set)
- Bin 0: -0.2773 bps
- Bin 1: -0.5718 bps
- Bin 2: -0.0306 bps
- Bin 3: 0.0691 bps
- Bin 4: 0.0855 bps
- Bin 5: 0.0309 bps
- Bin 6: 0.0000 bps
- Bin 7: 0.0000 bps
- Bin 8: 0.0000 bps
- Bin 9: 0.0000 bps
- Bin 10: 0.0000 bps
- Bin 11: 0.0000 bps
- Bin 12: 0.0000 bps
- Bin 13: 0.0000 bps
- Bin 14: -0.1238 bps

## Calibrated Expected Return per Bin
- Bin 0: -0.2773 bps
- Bin 1: -0.5718 bps
- Bin 2: -0.0306 bps
- Bin 3: 0.0691 bps
- Bin 4: 0.0855 bps
- Bin 5: 0.0309 bps
- Bin 6: 0.0000 bps
- Bin 7: 0.0000 bps
- Bin 8: 0.0000 bps
- Bin 9: 0.0000 bps
- Bin 10: 0.0000 bps
- Bin 11: 0.0000 bps
- Bin 12: 0.0000 bps
- Bin 13: 0.0000 bps
- Bin 14: -0.1238 bps

## Calibration Error per Bin (MAE)
- Bin 0: 0.1417 bps
- Bin 1: 0.3575 bps
- Bin 2: 0.1399 bps
- Bin 3: 0.1377 bps
- Bin 4: 0.1096 bps
- Bin 5: 0.0464 bps
- Bin 6: 0.0000 bps
- Bin 7: 0.0000 bps
- Bin 8: 0.0000 bps
- Bin 9: 0.0000 bps
- Bin 10: 0.0000 bps
- Bin 11: 0.0000 bps
- Bin 12: 0.0000 bps
- Bin 13: 0.0000 bps
- Bin 14: 0.0000 bps

## Expectancy Metrics
- Gross expectancy using calibrated return: 0.0797 bps (95% CI: [0.0064, 0.0145])
- Maker-adjusted expectancy: -1.9203 bps (95% CI: [-1.9937, -1.9851])
- Taker-adjusted expectancy: -4.0861 bps (95% CI: [-4.1595, -4.1511])
- Percentage of observations exceeding gate (4.67 bps): 0.00%

## Conditional Expectancy after Cost by Prediction-Strength Bin
- Low (|cal| ≤ 0.0691 bps): 0.0553 bps
- Medium (0.0691 < |cal| ≤ 0.0691 bps): 0.0000 bps
- High (|cal| > 0.0691 bps): 0.3021 bps

## Maximum Drawdown of Hypothetical Signal Series
- Max drawdown: 0.4148 bps

## Leakage Check
- Calibration max timestamp: 1787082620783
- OOS min timestamp: 1787082620885
- No leakage: True

## Data Quality Checks
- calibration_missing_pred: 0
- calibration_missing_label: 7
- oos_missing_pred: 0
- oos_missing_label: 7
- calibration_inf_pred: 0
- oos_inf_pred: 0

## Comparison with Untouched V5 Baseline
- Gross directional expectancy (sign(pred) * actual return): 0.0641 bps

## Conclusion
- **CALIBRATION_VALID_BUT_NO_EDGE**

## Note
- Live trading remains HARD-BLOCKED regardless of conclusion.
