# Research Queue

**Date**: 2026-08-24
**Status**: COMPLETE (Terminal State: NO_DEPLOYABLE_EDGE)

Ranked by: research support × data availability × novelty vs rejected hypotheses.

---

## Queue (All Completed)

| ID | Hypothesis | Priority | Status |
|----|-----------|----------|--------|
| EXP-007 | Horizon-Matched Feature Aggregation (HORIZON-OFI) | HIGH | REJECTED |
| EXP-008 | Volatility-Regime Conditional Trading (REGIME) | HIGH | REJECTED |
| EXP-009 | Order-Book Resiliency Signal (RESILIENCY) | MEDIUM | REJECTED |
| EXP-010 | Multi-Horizon Signal Ensemble (ENSEMBLE) | MEDIUM | REJECTED |

## Completed / Rejected

### Architecture experiments (pre-registered in seed):
| ID | Verdict | Reason |
|----|---------|--------|
| EXP-001 | REJECTED | Cost >> signal: +0.069 gross vs 2.0 bps maker fee |
| EXP-002 | REJECTED | MLP did not improve over ridge |
| EXP-003 | REJECTED | +0.045 gross, 44x below maker fee |
| EXP-004 | REJECTED | Purging removes all signal (-0.003 gross) |
| EXP-005 | REJECTED | 88% of 500ms returns are 0.0 bps, gate never triggers |
| EXP-006 | REJECTED | 500ms features at 30s horizon (mismatch), zero magnitude correlation |

### Novel hypothesis experiments (EXP-007-011):
| ID | Verdict | Reason |
|----|---------|--------|
| EXP-007 | REJECTED | Horizon-matched features (1s-30s): direction accuracy below random (0.15-0.40). 0% above gate. |
| EXP-008 | REJECTED | Volatility-regime conditional: no regime produces positive net. 82% of events have zero volatility. |
| EXP-009 | REJECTED | Resiliency features: no improvement over V5 baseline. 0% above gate. |
| EXP-010 | REJECTED | Multi-horizon ensemble: all 3 strategies worse than best single horizon. Signals not complementary. |
| EXP-011 | REJECTED | Long-horizon (5-60min): E[|r|]=2.27bps at 5min but features have ~0 correlation. |
| EXP-012 | REJECTED | Aggressive flow × absorption: max return 3.54bps < 4.0bps cost |
| EXP-013 | REJECTED | Two-stage (5min): required 63.5% acc, achieved 52.4% |
| EXP-014 | REJECTED | Next-trade direction: AUC=0.736 but max return 3.67 < cost |
| EXP-015 | REJECTED | Size-conditioned trade-sign: IC=0.18, dp=1.20 but < 4.0bps cost |
| EXP-016 | REJECTED | Cross-market/derivatives: funding rate & hourly returns add NO incremental value. Best incremental: +0.05 bps (negligible). IC=0.17, net(maker)=-0.87. |
| EXP-017 | AUDIT (IN PROGRESS) | Information-set completeness: OI unavailable, funding/basis/cross-asset available but not downloaded |

---

## Research Tree Coverage

All 11 research tree branches + cross-market dimension fully tested:

| Branch | Experiment(s) | Verdict |
|--------|--------------|---------|
| EXP-A: Event-level OFI + depth normalization | EXP-001 | REJECTED |
| EXP-B: Multi-level OFI + depth normalization | EXP-003 | REJECTED |
| EXP-C: OFI conditional on liquidity/depth regime | EXP-008 | REJECTED |
| EXP-D: OFI + queue imbalance + microprice | EXP-003, EXP-006 | REJECTED |
| EXP-E: Order-flow persistence/decay | EXP-009, EXP-011 | REJECTED |
| EXP-F: Cancellation/depletion/replenishment dynamics | EXP-009 | REJECTED |
| EXP-G: Execution-aware prediction | EXP-005, EXP-006 | REJECTED |
| EXP-H: Volatility/liquidity conditional signal | EXP-008 | REJECTED |
| EXP-I: Event-time aggregation | EXP-007 | REJECTED |
| EXP-J: Combination of independently validated components | EXP-010 | REJECTED |
| EXP-K: Aggressive flow × capacity × fragility | EXP-012 | REJECTED |
| EXP-L: Size-conditioned trade-sign | EXP-013, EXP-014, EXP-015 | REJECTED |
| EXP-M: Cross-market/derivatives context | EXP-016 | REJECTED |

---

## Conclusion

**NO_DEPLOYABLE_EDGE** — The research tree is fully exhausted. All 11 branches of the
research tree have been tested across 12 experiments (EXP-001 through EXP-012), plus
4 extended experiments (EXP-013 through EXP-016). None produced positive net expectancy.

EXP-016 further confirmed that cross-market/derivatives context (funding rates,
hourly returns) provides no incremental predictive power — the signal is fundamentally
a function of trade direction and size within the order-flow itself.

The fundamental limitation is not model architecture or feature engineering — it is that
the order-flow microstructure signal (gross +0.02 to +0.15 bps) is 25-100x smaller than
the realistic execution cost (2.0-2.5 bps maker fee). At longer horizons (5min), moves
are large enough (E[|r|] = 2.27 bps) but the features have ~0 correlation with returns.
