# V6 vs V5 Forensic Validation Report

- **Generated**: 2026-08-19T19:49:11.430602+00:00
- **Protocol**: Pre-registered V6 validation against immutable V5 baseline
- **Verdict**: **NO_EDGE**

## Verdict Reasons

- V6 net expectancy negative after contemporaneous cost: 0.0000 bps
- V6 gross expectancy statistically significant (HAC p=0.0000)
- V6 net expectancy NOT statistically significant (HAC p=1.0000)
- V6 NOT profitable in normal liquidity regime
- LONG/SHORT asymmetry detected (LONG=nan, SHORT=nan)
- V6 incremental R2 over V5: 0.000000
- V6 residual predictive power p=0.0000

## Side-by-Side Scoreboard

| metric | V5 | V6 |
|---|---|---|
| gross_expectancy_bps | 0.06408 | 0.071924 |
| gated_expectancy_bps | 0.0 | 0.0 |
| pf | 0.0 | 0.0 |
| sharpe | 0.0 | 0.0 |
| max_drawdown_bps | 0.0 | 0.0 |
| executed_rows | 0.0 | 0.0 |
| net_trail_n | 0.0 | 0.0 |

## Cost-Adjusted Analysis

| scenario | gate (bps) | gross (bps) | net (bps) | executed |
|---|---|---|---|---|
| historical_taker | 4.6658 | 0.0719 | 0.0000 | 0 |
| contemporaneous_taker | 4.6646 | 0.0719 | 0.0000 | 0 |
| contemporaneous_maker | 3.4396 | 0.0719 | -0.0010 | 1 |

## Incremental Information (V6 over V5)

- Prediction correlation: 0.5525
- V6 residual correlation with y: 0.1271
- V6 residual t-stat: 7.9817
- V6 residual p-value: 0.0000
- V5 R2: 0.000000
- V6 R2: 0.000000
- Incremental R2: 0.000000

## Regime Breakdown

| regime | n | executed | gross (bps) | net (bps) | gross p | net p |
|---|---|---|---|---|---|---|
| high_impact | 1383 | 0 | 0.0003 | 0.0000 | 0.9357 | 1.0000 |
| normal | 2506 | 0 | 0.1114 | 0.0000 | 0.0000 | 1.0000 |

## Deployment Gates

| criterion | status |
|---|---|
| net_positive_after_cost | FAIL |
| gross_statistically_significant | PASS |
| net_statistically_significant | FAIL |
| normal_regime_robust | FAIL |
| long_short_symmetric | FAIL |
| incremental_r2_positive | FAIL |

## Next Steps

- If CONDITIONAL_EDGE: proceed to independent replication on new untouched data.
- If NO_EDGE: report failure; do not optimize; investigate alternative feature engineering.
- Live trading remains BLOCKED until independent replication passes.

