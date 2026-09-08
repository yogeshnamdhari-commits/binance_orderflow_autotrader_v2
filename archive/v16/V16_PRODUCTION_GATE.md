# V16 — Production Gate (Corrected)

## Gate Summary
- **Overall Status**: PASS (scientific gates)
- **Production Authorized**: NO — requires explicit authorization
- **LIVE_ORDER_SUBMISSION**: FALSE (hard-disabled)

## Gate Table

| Gate | Status | Detail |
|------|--------|--------|
| calibration_data_present | PASS | data/v16/calibration, 5876 obs |
| forward_data_present | PASS | data/v16/forward, 5876 events |
| forward_temporal_separation | PASS | 273s gap |
| frozen_artifact_exists | PASS | v16_frozen_return_model.joblib + v16_frozen_fill_model.joblib |
| frozen_artifact_integrity | PASS | checksums verified |
| frozen_artifact_immutable | PASS | chmod 444 |
| forward_validation | **PASS** | net EV 2.15 bps, CI [1.76, 2.60], p=0.0005, 6/6 regimes |
| execution_cost_validation | PASS | total cost 1.72 bps |
| statistical_significance | **PASS** | p=0.0005, CI entirely positive |
| paper_trading | BLOCKED | not yet started |
| risk_controls | PASS | configured |
| config_integrity | PASS | hash e07dd90923983920 |
| live_order_submission | **FAIL** | hard-disabled |

## Accounting Verification
- **Formula**: Net EV = mean(fill_prob * predicted_return) - mean(total_cost)
- **NOT**: Gross EV - Total cost
- Gross EV = mean(|predicted_return|) over trades only
- Total cost = mean(entry + exit + conditional non_fill) over trades
- Non-fill cost = (1 - fill_prob) * 0.5 bps (conditional)

## Production Decision
All scientific gates PASS. Paper trading must be run before production authorization.
LIVE_ORDER_SUBMISSION remains FALSE.
