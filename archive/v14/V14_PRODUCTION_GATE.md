# V14 — Production Gate

## Gate Summary
- **Overall Status**: FAIL
- **Production Authorized**: NO
- **LIVE_ORDER_SUBMISSION**: FALSE (hard-disabled)

## Gate Table

| Gate | Status | Detail |
|------|--------|--------|
| calibration_data_present | PASS | data/v14/calibration exists, 3519 books + 9925 trades |
| forward_data_present | PASS | data/v14/forward exists, 3521 books + 6233 trades |
| forward_temporal_separation | PASS | cal_end < fwd_start, 698s gap |
| frozen_artifact_exists | PASS | archive/v14/v14_frozen_model.joblib |
| frozen_artifact_integrity | PASS | checksum matches, file immutable (chmod 444) |
| frozen_artifact_immutable | PASS | read-only file |
| forward_validation | **FAIL** | net EV 0.01 bps, CI [-2.55, 7.02], p=1.0 |
| execution_cost_validation | PASS | total cost 3.25 bps < 5.0 bps |
| robustness | BLOCKED | insufficient forward sample (7 trades) |
| statistical_significance | **FAIL** | CI includes zero, p=1.0 |
| paper_trading | BLOCKED | not enabled (forward gate failed) |
| risk_controls | PASS | stop_loss + max_holding configured |
| config_integrity | PASS | config_hash = 12e0e1775ee6b46d |
| live_order_submission | **FAIL** | hard_disabled = True |

## Mandatory Gate Failures
1. **forward_validation FAIL**: net EV ≈ 0, CI includes zero, p-value = 1.0
2. **statistical_significance FAIL**: edge not distinguishable from zero

## Production Decision
- Production remains LOCKED.
- LIVE_ORDER_SUBMISSION is hard-disabled.
- No live orders will be submitted without explicit authorization.
