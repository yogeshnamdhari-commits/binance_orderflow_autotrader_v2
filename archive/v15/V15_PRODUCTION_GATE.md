# V15 — Production Gate

## Gate Summary
- **Overall Status**: FAIL
- **Production Authorized**: NO
- **LIVE_ORDER_SUBMISSION**: FALSE (hard-disabled)

## Gate Table

| Gate | Status | Detail |
|------|--------|--------|
| calibration_data_present | PASS | data/v15/calibration, 5866 books + 21374 trades |
| forward_data_present | PASS | data/v15/forward, 5871 books + 6812 trades |
| forward_temporal_separation | PASS | cal_end < fwd_start, 135s gap |
| frozen_artifact_exists | PASS | archive/v15/v15_frozen_model.joblib |
| frozen_artifact_integrity | PASS | checksum c48e95d537822367 |
| frozen_artifact_immutable | PASS | chmod 444 |
| forward_validation | **FAIL** | net EV -1.69 bps, CI [-2.11, -1.02], p=0.991, 0/6 regimes |
| execution_cost_validation | PASS | total cost 1.61 bps |
| robustness | BLOCKED | 0/6 regimes positive |
| statistical_significance | **FAIL** | p=0.991, CI entirely negative |
| paper_trading | BLOCKED | not enabled |
| risk_controls | PASS | configured |
| config_integrity | PASS | hash aa505ca8abe09376 |
| live_order_submission | **FAIL** | hard-disabled |

## Production Decision
Production remains LOCKED.
