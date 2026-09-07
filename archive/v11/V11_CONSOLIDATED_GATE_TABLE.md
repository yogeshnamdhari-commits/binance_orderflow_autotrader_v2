# V11 CONSOLIDATED GATE TABLE

**Version:** V11
**Date:** 2026-09-05
**Overall Status:** FAILED

---

## GATE TABLE

| Gate | Status | Evidence | Blocker / Exact Path |
|------|--------|----------|---------------------|
| Research/OOS | PASS | Gradient boosting trained on 2,298 calibration observations. Test AUC = 0.5974. Model frozen with checksum 52ac9a4a2b4ccda8. | — |
| Data provenance | PASS | Calibration: 4 sessions from 2026-09-05 morning. Forward: 1 session from 2026-09-05 after calibration. All data hashed and archived. | — |
| Frozen model | PASS | `archive/v11/v11_frozen_model.joblib` checksum verified. Model frozen before forward exposure. | — |
| Independent forward test | FAIL | Forward gross EV = -0.5388 bps. Net EV = -1.7116 bps. 95% CI = [-1.9288, -1.4951]. Signal is negative and perverse in forward data. | `archive/v11/v11_forward_result.json` |
| Execution-cost validation | FAIL | Total cost = 1.0526 bps (taker 5.0 + slippage 0.5 + adverse 0.5 + latency 0.1, fill-prob weighted). Breakeven = 35.47 bps. Model predicted return = 0.1647 bps. Gap = 215x. | `archive/v11/V11_ECONOMIC_DIAGNOSIS.json` |
| Regime robustness | FAIL | All regimes show negative net EV when corrected for spread. Signal magnitude insufficient across all market conditions. | `archive/v11/v11_forward_result.json` (regimes section) |
| Statistical robustness | FAIL | One-sided p-value = 1.0. 95% CI excludes zero in wrong direction. Cohen's d = -0.4492 (large negative effect). Permutation p-value = 1.0. | `archive/v11/v11_forward_result.json` |
| Evidence-chain integrity | PASS | Pre-registered protocol frozen at 2026-09-05T09:02:22+05:30. No parameters, thresholds, features, or models changed after forward exposure. No p-hacking. | `archive/v11/V11_PRE_REGISTERED_PROTOCOL.md` |
| Paper trading | BLOCKED | Requires all prior gates to pass. Multiple blockers: negative net EV, statistical insignificance, regime failure. | — |
| Production authorization | BLOCKED | Requires paper trading success + authorization. Not applicable. | — |

---

## KEY METRICS SUMMARY

| Metric | Value |
|--------|-------|
| Calibration observations | 2,298 |
| Forward observations | 1,159 |
| Model AUC (train/val/test) | 0.6669 / 0.6148 / 0.5974 |
| Forward gross EV | -0.5388 bps |
| Forward net EV (taker) | -1.7116 bps |
| Total execution cost | 1.0526 bps |
| Fill probability | 17.2% |
| Breakeven return | 35.47 bps |
| Actual market spread | 0.013 bps |
| 95% CI (net EV) | [-1.9288, -1.4951] |
| p-value (one-sided) | 1.0 |
| Permutation p-value | 1.0 |
| Cohen's d | -0.4492 |
| Prediction-actual correlation (forward) | -0.0424 |

---

## SCIENTIFIC CONCLUSION

V11 tested whether gradient-boosted order-flow modeling could overcome the BTCUSDT execution cost barrier. The experiment FAILED.

The order-flow signal is:
1. **Negative** in forward data
2. **Statistically insignificant**
3. **215x below breakeven**
4. **Temporally unstable**
5. **Negatively correlated** with actual returns

This confirms the data-theoretic limitation documented in prior research (V5-V10): the Binance BTCUSDT order-flow microstructure does not contain sufficient predictable information to overcome realistic taker execution costs at the 500ms horizon.

---

**END OF CONSOLIDATED GATE TABLE**
