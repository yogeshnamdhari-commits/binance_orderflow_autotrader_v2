# V19 Economic Order-Flow Correction Design

**Date:** 2026-09-09
**Base:** `v18-information-set-expansion`
**Control:** frozen V16 production candidate

## Goal

Develop a smaller, economically motivated order-flow research candidate that can beat V16 on unseen Binance L2 data after realistic execution costs, without changing V16 or enabling live orders during research.

## Research basis

The design follows established microstructure evidence that short-horizon price changes are strongly related to order-flow imbalance and available depth, rather than relying on raw trade direction alone (Cont, Kukanov, Stoikov). Fill probability is treated as a distinct execution problem because passive execution depends on queue dynamics and time-to-fill. Model selection is constrained by leakage control, purged/embargoed chronological validation, and explicit protection against repeated backtest selection.

## Architecture

1. **V16 frozen control:** no source changes; all V19 results are compared directly with the existing V16 evidence.
2. **Compact information set:** retain only causally available L2/order-flow variables with demonstrated microstructure rationale: multi-level OFI/depth pressure, signed trade flow, spread/liquidity state, queue-change intensity and short-horizon state transitions. V18 liquidation/funding/cross-market families are not carried forward automatically.
3. **Separate targets:** a regularized return model predicts forward mid-price/value movement; a separate fill model estimates passive execution probability. They are combined only in an expected-net-P&L decision function.
4. **Execution economics:** maker/taker costs, spread, adverse-selection/slippage and non-fill opportunity cost are explicit. No gross-EV-only selection.
5. **Validation:** chronological, purged/embargoed walk-forward splits; all feature transforms fit only on training observations. Historical L2 replay is the decisive unseen-data test.
6. **Robustness:** chronological blocks, cost stress, leave-one-regime-out and feature-family ablations. The candidate is rejected if the improvement depends on one regime or disappears under modest cost stress.
7. **Governance:** `LIVE_ORDER_SUBMISSION` remains hard-disabled throughout research.

## Acceptance criteria

V19 may become a production candidate only if all are true:

- V19 net EV is materially above V16 on the independent forward set.
- V19 also improves or at minimum does not materially deteriorate on unseen historical L2 replay.
- Realized net EV agrees with modeled net EV within the pre-specified confidence interval.
- The confidence interval for incremental performance excludes zero at the pre-registered significance level.
- Positive performance survives every chronological regime block and the prescribed cost-stress test.
- No leakage or future-data dependency is detected.
- All tests and evidence-generation checks pass.

AUC improvement without economic improvement is not a pass. A positive backtest that results from repeated feature/parameter selection is not a pass.

## Research guardrail

The project must not promise a positive result in advance. If V19 fails the acceptance criteria, V16 remains the control/production candidate and V19 is rejected; further feature expansion requires a new approved research hypothesis.
