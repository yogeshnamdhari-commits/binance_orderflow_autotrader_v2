# Deployment Gate

## Gate Status: BLOCKED

## Required Conditions

| Condition | Status | Value | Required |
|-----------|--------|-------|----------|
| DATA_OK | PASS | Data integrity verified (0 errors, 54 warnings) | TRUE |
| LABEL_OK | PASS | Chronological, no look-ahead | TRUE |
| LEAKAGE_OK | PASS | Purged validation, no future data | TRUE |
| OOS_OK | PASS | Sessions held out for OOS | TRUE |
| WALK_FORWARD_OK | PASS | 2-fold walk-forward completed | TRUE |
| COST_MODEL_OK | PASS | 4.0 bps taker (measured) | TRUE |
| NET_EXPECTANCY_CI_POSITIVE | **FAIL** | -3.80 bps (EXP-013), CI [-3.82, -3.78] | **> 0** |
| ROBUSTNESS_OK | PASS | Multiple regimes tested | TRUE |
| EXECUTION_SIMULATION_OK | PASS | Cost model verified | TRUE |
| RISK_LIMITS_OK | PASS | Risk engine configured | TRUE |
| ORCHESTRATOR_OK | PASS | State machine functional | TRUE |

## Primary Blocking Condition

**NET_EXPECTANCY_CI_POSITIVE = FALSE**

After 13 experiments across 12 research domains:
- EXP-001 to EXP-012: All REJECTED (short-horizon order flow prediction)
- EXP-013: REJECTED (two-stage event + direction prediction)

The fundamental constraint is now fully characterized:

1. **Trade-sign signal** has IC = 0.01-0.15 across horizons
2. **Book features** have IC = 0.26 for direction but only on V4 session data (no large moves)
3. **730-day trade data** has large moves (80.6% event rate at 5min) but trade-sign IC = 0.01
4. **No data source combines** both book features AND large moves at the same horizon
5. **Required accuracy** for breakeven: 57-63% (maker/taker cost ratio)
6. **Achieved accuracy**: 52.4% (V4 book features) — gap of 4-11 percentage points

### Perfect Prediction Bounds

| Horizon | Perfect Net (taker) | Perfect Net (maker) | Required Accuracy |
|---------|--------------------|--------------------|-------------------|
| 10s | -1.08 bps (negative) | +1.60 bps | Impossible (>100%) |
| 30s | +1.85 bps | +3.87 bps | 87.5% / 68.7% |
| 60s | +4.27 bps | +6.28 bps | 77.2% / 63.6% |
| 5min | +11.77 bps | +13.78 bps | 63.1% / 56.5% |

Even with perfect prediction, 10s horizon yields **negative** net expectancy.

## Secondary Blocking Condition

**V5_BASELINE_NO_LIVE_TRADE = True** in `app/config.py`

This hard block prevents any trading decision from being executed.
The block is intentional and must NOT be removed until all above gates pass.
