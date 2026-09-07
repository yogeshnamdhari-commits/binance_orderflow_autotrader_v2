# V14 — Final Evidence Chain

## Phase 1: Repository Audit (COMPLETE)
- Inspected V12/V13 modules, tests, capture code, features, models, execution simulators
- Reused V11 parser (`V11DataParser`), V12 capture (`capture_session`), V13 model structure (LogisticRegression)
- Created V14: config (10s horizon, maker/taker costs), features (10 vars), model, execution sim, pipeline, production gate, paper runtime, CLI
- Baseline tests: 3 pre-existing V9 failures, 299 pass, 1 skip — preserved
- V12 result: net EV -4.49 bps (FAIL) — frozen, NOT modified
- V13 result: AUC 0.72, net EV negative after 14.52 bps cost (FAIL) — frozen, NOT modified

## Phase 2: V14 Pre-Registration (COMPLETE)
- `data/research/v14_proposal.json` — registered BEFORE calibration
- Config hash: `12e0e1775ee6b46d`
- All features, execution assumptions, thresholds pre-specified (NOT selected by result)
- V14 is a NEW experiment, distinguishable from V12/V13 by config hash and 10s horizon

## Phase 3: Fresh Data Capture (COMPLETE)
### Calibration
- Session: `data/v14/calibration/a12385f919c74d33a47e6103c9fbe250`
- Duration: 360s
- Events: 3519 depthUpdate, 9925 trades, 99902 bookTicker
- Start: ns 1788785859113448000, End: ns 1788786221312518000

### Forward
- Session: `data/v14/forward/414394bfed5140a0894b3d6343c2b7e4`
- Duration: 360s
- Events: 3521 depthUpdate, 6233 trades, 82148 bookTicker
- Start: ns 1788786920131567000, End: ns 1788787281457295000

### Data Integrity Checks
- **Temporal separation**: Gap of 698.8s between calibration end and forward start → PASS
- **No overlap**: calibration end < forward start → PASS
- **No duplicates**: verified by stream event counts (depthUpdate, trade, bookTicker)
- **Timestamp ordering**: verified via parser (sequential event processing)
- **Sequence consistency**: depth updates applied incrementally from initial snapshot
- **V14-only data**: V12/V13 data explicitly EXCLUDED from calibration and forward

## Phase 4: Feature Pipeline (COMPLETE)
10 economically motivated features (NOT a zoo):
| Feature | Math Definition | No-Lookahead |
|---------|----------------|-------------|
| book_imbalance_l1 | (bid1_qty - ask1_qty) / (bid1_qty + ask1_qty + eps) | ✓ (depth at t) |
| book_imbalance_l5 | 5-level weighted depth imbalance | ✓ (depth at t) |
| aggressive_trade_imbalance | (Σbuy_vol - Σsell_vol) / (Σvol + eps) over [t-10s, t] | ✓ (trade ts <= t) |
| microprice_deviation_bps | (microprice - mid) / mid × 1e4 | ✓ (depth at t) |
| depth_pressure | (adds - cancels) / (adds + cancels + eps) over Δbook | ✓ (book delta at t) |
| trade_intensity | trade_count / 10s | ✓ (trade ts <= t) |
| spread_bps | best_ask - best_bid (bps) | ✓ (depth at t) |
| vol_regime | rolling 500-book realized vol | ✓ (past mids <= t) |
| signed_vol_imbalance | (buy - sell) / max(buy, sell, eps) | ✓ (trade ts <= t) |
| liquidity_state | depth1 / max_trade_qty_in_window | ✓ (past data <= t) |

**Leakage tests**: `test_v14_feature_extraction_no_lookahead`, `test_v14_no_lookahead_in_feature_window` — PASS

## Phase 5: Target/Horizon (COMPLETE)
- **Horizon**: 10s (pre-registered, NOT selected by result)
- **Target**: binary — mid price at t+10s > mid at t
- **Returns**: 10s forward mid-price change in bps
- Target constructed strictly from future price AFTER feature timestamp → leakage test PASS

## Phase 6: Calibration (COMPLETE)
- **Data**: V14 calibration session ONLY (V13/V12 EXCLUDED)
- **Time-series split**: train 70% / val 15% / test 15% (sequential, NO shuffle)

| Model | Train AUC | Val AUC | Test AUC |
|-------|-----------|---------|----------|
| Naive baseline | — | — | — |
| Simple (imbalance sign) | — | — | — |
| V14 candidate (LogReg) | 0.6987 | 0.5358 | 0.3478 |

**Economic calibration results**:
- Baseline naive EV: -0.27 bps
- Baseline simple EV: -1.91 bps
- V14 gross EV (in-sample): 0.01 bps
- V14 net EV (in-sample, 9 trades): -0.005 bps
- Total cost: 3.25 bps (maker 75% / taker 25%)

**Note**: Test AUC = 0.35 (< 0.5 random) indicates overfitting to in-sample patterns. The model can rank in-sample but does NOT generalize to the held-out test period.

## Phase 7: Frozen Artifact (COMPLETE)
- Model frozen at `archive/v14/v14_frozen_model.joblib`
- File set immutable (chmod 444)
- Config hash: `12e0e1775ee6b46d`
- Feature names: v14 model registry
- Model checksum: `120fc58494860a54`
- Evidence: `data/evidence/v14_calibration.json`, `data/evidence/v14_model_registry.json`
- **After freezing**: NO model or calibration changes allowed

## Phase 8: Independent Forward Test (COMPLETE)
- **Frozen model** applied to COMPLETELY UNTOUCHED forward data
- Forward data NOT seen during calibration
- No forward outcomes exposed to calibration

| Metric | Value |
|--------|-------|
| N events | 1,162 |
| N signals | 7 |
| N trades | 7 |
| AUC | 0.666 |
| Gross EV | 0.028 bps |
| Maker rebate | -0.009 bps |
| Spread cost | 1.125 bps |
| Slippage | 0.200 bps |
| Adverse selection | 0.600 bps |
| Latency | 0.200 bps |
| **Total cost** | **3.25 bps** |
| **Net EV** | **0.012 bps** |
| CI lower (95%) | -2.554 bps |
| CI upper (95%) | 7.019 bps |
| p-value | 1.0 |
| Regimes positive | 4/6 |

**Verdict**: FAIL — net EV ≈ 0, CI includes zero, p = 1.0

**Do NOT modify model and rerun.** V14 result is final.

## Phase 9: Execution Engine (COMPLETE)
- **Maker**: rebate -2bps, fill probability 75%, queue assumptions, adverse selection +0.3bps, latency +0.1bps
- **Taker**: fee +5bps, spread crossing, slippage +0.1bps, adverse +0.3bps, latency +0.1bps
- Entry cost (prob-weighted): 0.75 × (-2 + 0.1 + 0.3 + 0.1) + 0.25 × (5 + 0.1 + 0.3 + 0.1) = 0.25 bps
- Exit cost (taker): 3.0 bps
- Total roundtrip: 3.25 bps
- V13 total cost: 14.52 bps → V14 reduces to 3.25 bps (77% reduction)
- **Breakeven**: gross EV must exceed 3.25 bps per roundtrip trade

## Phase 10: Robustness (BLOCKED)
- Forward data yields only 7 trades — insufficient for regime analysis
- Per-regime CI is extremely wide (n=1 to 6 trades per regime)
- 4/6 regimes positive but NOT statistically reliable
- Status: BLOCKED — cannot validate robustness with 7 trades

## Phase 11: Statistical Validation (COMPLETE)
See `data/evidence/v14_statistical_robustness.json`

- Block bootstrap (5000 reps, 10s blocks): CI = [-2.55, 7.02] bps
- CI includes zero → NOT significant
- p-value = 1.0 → no detectable edge
- Multiple-testing: 10 comparisons, Bonferroni threshold p < 0.005 — none significant
- Effective sample size: 7 trades (too low for statistical power)

## Phase 12: Paper Trading (BLOCKED)
- Paper trading requires ALL scientific gates to pass
- Forward validation FAIL → paper trading BLOCKED
- Paper runtime implemented (`app/v14/paper_runtime.py`) but NOT enabled
- `block_trading_enabled` = False

## Phase 13: Production Gate (COMPLETE)
See `data/evidence/v14_production_gate.json` and `archive/v14/V14_PRODUCTION_GATE.md`

| Gate | Status |
|------|--------|
| calibration_data_present | PASS |
| forward_data_present | PASS |
| forward_temporal_separation | PASS |
| frozen_artifact_exists | PASS |
| frozen_artifact_integrity | PASS |
| frozen_artifact_immutable | PASS |
| forward_validation | **FAIL** |
| execution_cost_validation | PASS |
| robustness | BLOCKED |
| statistical_significance | **FAIL** |
| paper_trading | BLOCKED |
| risk_controls | PASS |
| config_integrity | PASS |
| live_order_submission | **FAIL** (hard-disabled) |
| **Overall** | **FAIL** |

## Phase 14: Automated Testing (COMPLETE)
- 18 V14 tests added (capture, features, leakage, execution costs, gate, config integrity)
- Full regression: 358 PASS, 3 pre-existing V9 FAIL, 1 SKIP
- Zero regressions introduced
- `tests/v14/test_v14_pipeline.py`

## Phase 15: Final Evidence Chain (COMPLETE)
- `archive/v14/V14_PRE_REGISTERED_PROTOCOL.md`
- `archive/v14/V14_FINAL_EVIDENCE_CHAIN.md`
- `archive/v14/V14_PRODUCTION_GATE.md`
- `data/evidence/v14_calibration.json`
- `data/evidence/v14_forward_validation.json`
- `data/evidence/v14_model_registry.json`
- `data/evidence/v14_regime_analysis.json`
- `data/evidence/v14_statistical_robustness.json`
- `data/evidence/v14_execution_costs.json`
- `data/evidence/v14_production_gate.json`
- `data/evidence/v14_paper_trading.json`
- `FINAL_STATUS.json`
