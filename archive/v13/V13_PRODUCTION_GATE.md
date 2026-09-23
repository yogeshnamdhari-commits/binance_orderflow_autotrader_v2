# V13 Production Gate Report

**Generated:** 2026-09-07  
**Live order submission:** `LIVE_ORDER_SUBMISSION = False` (hard code-level lock, Rule 28)  
**Overall status:** LOCKED

## Gate Evaluation

| Gate | Status | Evidence |
|------|--------|----------|
| data_integrity | PASS | 2 capture sessions validated (41,060 / 45,466 events) |
| data_provenance | PASS | Real Binance WebSocket + REST, SHA-256 checksums |
| no_leakage | PASS | Temporal separation verified, chronological split |
| model_calibration | PASS | Val AUC 0.72, train ≈ val (no overfitting) |
| frozen_artifact | PASS | `v13_frozen_model.joblib` exists, immutable |
| independent_forward_test | **FAIL** | status=FAIL |
| positive_net_ev | **FAIL** | -5.92 bps |
| realistic_execution_costs | PASS | 14.52 bps (Binance taker + realistic slippage) |
| statistical_robustness | **FAIL** | p=1.0, CI entirely negative |
| regime_robustness | **FAIL** | 0/6 regimes positive |
| paper_trading | BLOCKED | Forward gate FAILED |
| testnet_execution | BLOCKED | Credentials unavailable |
| risk_controls | PASS | V12RiskEngine wired |
| reconciliation | PASS | reconcile_position implemented |
| operational_failure_tests | NOT_STARTED | — |
| evidence_chain | PASS | `V13_FINAL_EVIDENCE_CHAIN.md` exists |

## Lock Reasons

1. **Forward gate FAIL** — net EV -5.92 bps, not statistically significant.
2. **`LIVE_ORDER_SUBMISSION = False`** — hard code-level constant (Rule 28).

## Primary Insight

V13 improved statistical discrimination (AUC 0.50→0.72) but revealed the deeper problem: **statistical signal ≠ economic value**. The order-flow signal can rank trades but its return magnitude (~0 bps) is below the execution-cost floor (14.52 bps) at the 2-second horizon.

## Next Experiment (V14)

**Hypothesis:** Replacing market-sweep (taker) execution with passive maker-queue placement will reduce effective execution cost from 14.52 bps to ≤3 bps, allowing the existing 2s-horizon signal (AUC 0.72) to achieve positive net EV.

This requires:
- V14 passive order-book submission engine
- Maker rebate modeling (0.02% vs 0.05% taker)
- Queue position simulation
- New real data capture (V14 calibration must not reuse V13 forward data)
