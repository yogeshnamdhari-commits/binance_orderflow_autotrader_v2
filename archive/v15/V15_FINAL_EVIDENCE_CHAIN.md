# V15 — Final Evidence Chain

## Phase 1: Repository Audit (COMPLETE)
- Inspected V12/V13/V14 modules, tests, capture code, features, models, execution simulators
- Reused V11 parser, V12 capture, V14 features, V14 execution model
- Created V15: config (10s horizon, execution-aware), features (13 vars), regime filter, GBR model, execution router, pipeline, gate, CLI
- Baseline: 3 pre-existing V9 failures, 380 pass, 1 skip — preserved
- V12/V13/V14 results frozen, NOT modified

## Phase 2: V15 Pre-Registration (COMPLETE)
- `data/research/v15_proposal.json` — registered BEFORE calibration
- Config hash: `aa505ca8abe09376`
- Hypothesis: execution-aware router + regime filter + GBR return-magnitude prediction will achieve positive net EV
- Model: GradientBoostingRegressor (predicts return magnitude in bps)
- Safety margin: 1.0 bps
- Regime filter: high vol + high liquidity + tight spread

## Phase 3: Fresh Data Capture (COMPLETE)
### Calibration
- Session: `data/v15/calibration/5483f2fb6c664d549bb0de8415df194d`
- Duration: 600s
- Events: 5866 depthUpdate, 21374 trade, 162979 bookTicker
- Start: ns 1788809935742398000, End: ns 1788810070776780000

### Forward
- Session: `data/v15/forward/236aab13fa14441b9235a7beb81df682`
- Duration: 600s
- Events: 5871 depthUpdate, 6812 trade, 80731 bookTicker
- Start: ns 1788810070776780000, End: ns 1788810130776780000

### Data Integrity
- Temporal separation: PASS (calibration end < forward start)
- No overlap, no duplicates, ordered timestamps

## Phase 4: Feature Pipeline (COMPLETE)
- 13 features: 10 V14 order-flow + 3 regime flags (vol, liquidity, spread)
- All causally computed, no lookahead
- Leakage tests: PASS

## Phase 5: Target/Horizon (COMPLETE)
- Horizon: 10s (pre-registered)
- Target: 10s forward mid-price return in bps
- Model: GBR predicting return magnitude (not just direction)

## Phase 6: Calibration (COMPLETE)
- N obs: 5866
- Train MAE: 0.94 bps, Val MAE: 1.84 bps, Test MAE: 2.48 bps
- Train R²: 0.82, Val R²: -0.37, Test R²: -0.04
- Gross EV (in-sample): 1.46 bps
- Net EV (in-sample): 1.92 bps (110 trades)
- Model frozen at `archive/v15/v15_frozen_model.joblib` (immutable)

## Phase 7: Frozen Artifact (COMPLETE)
- Model frozen, checksum: `c48e95d537822367`
- Config hash: `aa505ca8abe09376`
- File immutable (chmod 444)

## Phase 8: Independent Forward Test (COMPLETE)
- Frozen model on untouched forward data

| Metric | Value |
|--------|-------|
| N events | 5,871 |
| N regime pass | 927 |
| N signals/trades | 265 |
| Gross EV | 1.368 bps |
| Total cost | 1.606 bps |
| **Net EV** | **-1.687 bps** |
| CI lower | -2.113 bps |
| CI upper | -1.018 bps |
| p-value | 0.991 |
| Regimes positive | 0/6 |

**Verdict**: FAIL — net EV negative, CI entirely negative, 0/6 regimes positive

## Phase 9: Execution Engine (COMPLETE)
- Maker: rebate -2bps, entry cost -1.5bps (net credit), fill prob 75%
- Taker: fee +5bps, entry cost +5.5bps
- Exit cost: 3.0 bps
- Safety margin: 1.0 bps
- Router: MAKER if pred_return > 2.5bps, TAKER if pred_return > 9.5bps
- All-in maker cost: 1.61 bps (much lower than V14's 3.25 bps)

## Phase 10: Robustness (BLOCKED)
- Forward result negative across all regimes (0/6 positive)
- Not further tested

## Phase 11: Statistical Validation (COMPLETE)
- CI: [-2.11, -1.02] bps (entirely negative)
- p-value: 0.991 (not significant)
- Edge NOT distinguishable from zero

## Phase 12: Paper Trading (BLOCKED)
- Forward validation FAIL → BLOCKED

## Phase 13: Production Gate (COMPLETE)
- forward_validation: FAIL
- statistical_significance: FAIL
- Overall: FAIL, LIVE_ORDER_SUBMISSION = FALSE

## Phase 14: Automated Testing (COMPLETE)
- 10 V15 tests (all pass)
- Full regression: 381 pass, 3 pre-existing V9 failures, 1 skip
- Zero regressions

## Phase 15: Final Evidence Chain (COMPLETE)
- `archive/v15/V15_FINAL_EVIDENCE_CHAIN.md`
- `archive/v15/V15_PRODUCTION_GATE.md`
- `data/evidence/v15_*.json`
- `FINAL_STATUS.json`
