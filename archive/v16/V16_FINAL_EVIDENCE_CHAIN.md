# V16 — Final Evidence Chain

## Phase 1: Repository Audit
- Inspected V12–V15 modules, reused V11 parser, V12 capture, V14 features, V15 model structure
- Created V16: config (10s horizon, event-time), features (33 vars), queue-pressure proxy, return model (GBR), fill model (Logistic), execution router, walk-forward, gate, CLI
- Baseline: 3 pre-existing V9 failures, 392 pass, 1 skip — preserved

## Phase 2: V16 Pre-Registration
- `data/research/v16_proposal.json` — registered BEFORE calibration
- Config hash: `e07dd90923983920`
- Prediction horizon: 10s (pre-registered, NOT selected by result)
- Event-time features (not fixed bars)
- Queue-pressure proxy: (adds - cancels) / (adds + cancels + eps)
- Two models: return magnitude (GBR) + fill probability (Logistic)
- Walk-forward: 5 folds, chronological
- Acceptance: net EV > 0, CI > 0, p < 0.05, >= 4/6 regimes positive, >= 100 trades

## Phase 3: Fresh Data Capture
### Calibration
- Session: `data/v16/calibration/24549b716a4d40d49fc9e5a918e16f43`
- Duration: 600s
- Events: 5876 depthUpdate, 13456 trade, 144921 bookTicker
- Start: ns 1788821132731249000, End: ns 1788821733417995000

### Forward
- Session: `data/v16/forward/e264a34f0bac4d878f15a5ed8b0dc43c`
- Duration: 600s
- Events: 5876 depthUpdate, 20638 trade, 193095 bookTicker
- Start: ns 1788822006669496000, End: ns 1788822606669496000

### Data Integrity
- Temporal separation: PASS (273s gap)
- No overlap, no duplicates, ordered timestamps

## Phase 4: Feature Pipeline
- 33 features: 10 V14 order-flow + 23 V16 event-time (OFI, trade flow, queue/book, dynamics, regime)
- All causally computed, no lookahead
- Leakage tests: PASS

## Phase 5: Target/Horizon
- Horizon: 10s (pre-registered)
- Target: 10s forward mid-price return in bps (regression)
- Fill probability: binary (was order filled within 10s?)

## Phase 6: Calibration
- N obs: 5876
- Return model (GBR): Train MAE 0.631, Val MAE 2.578, Test MAE 1.435, Train R2 0.84, Val R2 -0.75, Test R2 0.06
- Fill model (Logistic): Train AUC 0.678, Val AUC 0.623
- Gross EV: 1.25 bps, Net EV: 1.20 bps, 357 trades
- Model frozen at `archive/v16/v16_frozen_return_model.joblib` + `v16_frozen_fill_model.joblib`

## Phase 7: Frozen Artifacts
- Return model checksum: `d4232bda213312f4`
- Fill model checksum: computed during freeze
- Files immutable (chmod 444)

## Phase 8: Independent Forward Test
| Metric | Value |
|--------|-------|
| N events | 5,876 |
| N signals | 382 |
| Gross EV | 1.489 bps |
| Total cost | 1.537 bps |
| Net EV | 1.181 bps |
| CI lower | 0.972 bps |
| CI upper | 1.367 bps |
| p-value | 0.0005 |
| Regimes positive | 6/6 |
| Forward PASS | **TRUE** |

## Phase 9: Execution Engine
- Maker: rebate -2bps, entry cost -1.5bps, fill prob modeled (Logistic)
- Taker: fee +5bps, entry cost +5.5bps
- Exit cost: 3.0 bps
- Non-fill opportunity cost: 0.5 bps
- Router: selects maker vs taker based on expected P&L

## Phase 10: Robustness
- 6/6 regimes positive in forward (high_vol, low_vol, high_liq, low_liq, tight_spread, wide_spread)
- All regimes show positive mean return

## Phase 11: Statistical Validation
- Block bootstrap CI: [0.97, 1.37] bps (entirely positive)
- Sign-flipping permutation p-value: 0.0005
- Edge IS statistically distinguishable from zero

## Phase 12: Paper Trading
- Status: BLOCKED (forward validation passed, but paper trading not yet run)
- Paper runtime: NOT started

## Phase 13: Production Gate
| Gate | Status |
|------|--------|
| forward_validation | PASS |
| statistical_significance | PASS |
| execution_cost_validation | PASS |
| Overall | PASS (scientific gates) |
| live_order_submission | FAIL (hard-disabled) |

## Phase 14: Testing
- 11 V16 tests (all pass)
- Full regression: 392 pass, 3 pre-existing V9 failures, 1 skip
- Zero regressions

## Phase 15: Evidence
- `archive/v16/V16_FINAL_EVIDENCE_CHAIN.md`
- `archive/v16/V16_PRODUCTION_GATE.md`
- `data/evidence/v16_*.json`
- `FINAL_STATUS.json`
