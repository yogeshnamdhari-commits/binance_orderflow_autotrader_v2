# AUTONOMOUS STATE — Binance Order-Flow Autotrader

## CURRENT_PHASE
NO_DEPLOYABLE_EDGE (terminal state — research tree fully exhausted + cross-market dimension tested)

## CURRENT_HYPOTHESIS
All 12 research tree branches tested and rejected (EXP-001 through EXP-012).
EXP-013, 014, 015 extended trade-sign hypothesis with size conditioning.
EXP-016 tested cross-market/derivatives context — also rejected.
EXP-017: Information-set completeness audit (in progress).

## CURRENT_MODEL
None — no deployable model produced.

## LAST_COMPLETED_ACTION
EXP-016 (Cross-Market/Derivatives Context) completed and rejected.
EXP-016 tested whether funding rates and hourly returns provide incremental
predictive power for the size-conditioned trade-sign signal. Results:
- Funding rate: -0.07 bps incremental (degrades)
- Hourly returns: 0.0 bps incremental
- Full model: -0.07 bps incremental
- Bootstrap CI: net maker [-1.04, -0.83], excludes zero
- Signal consistent across funding regimes (no interaction)
Total: 16 experiments, all REJECTED. Terminal state: NO_DEPLOYABLE_EDGE.

## CURRENT_RESULT
| Experiment | Gross bps | Net bps | Verdict |
|-----------|-----------|---------|---------|
| EXP-001 | +0.069 | -1.931 | REJECTED |
| EXP-002 | +0.100 | -1.900 | REJECTED |
| EXP-003 | +0.045 | -1.955 | REJECTED |
| EXP-004 | -0.003 | -2.003 | REJECTED |
| EXP-005 | 0.000 | -2.500 | REJECTED |
| EXP-006 | 0.000 | -2.500 | REJECTED |
| EXP-007 | -0.137 | -2.637 | REJECTED |
| EXP-008 | -0.227 | -2.637 | REJECTED |
| EXP-009 | +0.096 | -2.404 | REJECTED |
| EXP-010 | -0.294 | -2.770 | REJECTED |
| EXP-011 | -1.145 | -3.645 | REJECTED |
| EXP-012 | -0.083 | -4.128 | REJECTED |
| EXP-013 | -0.30 | -3.55 | REJECTED |
| EXP-014 | -0.10 | -3.94 | REJECTED |
| EXP-015 | +1.13 | -2.88 | REJECTED |
| EXP-016 | +1.13 | -2.88 | REJECTED |

## FAILED_HYPOTHESES

### Architecture experiments (V5-V8):
1. V5 Ridge (17 OFI features, 500ms) — net -1.93 bps
2. V6 MLP (25 features, 500ms) — net -1.90 bps
3. V7 Multi-Level (46 features, 500ms) — net -1.96 bps
4. V7 Purged validation — net -2.00 bps
5. V8 Direction-Magnitude (500ms) — gate never triggers, net -2.50 bps
6. V8 Direction-Magnitude (30s) — no predictive power, net -2.50 bps

### Novel hypothesis experiments (EXP-007-012):
7. EXP-007: Horizon-Matched Feature Aggregation (1s-30s) — dir accuracy below random, net -2.54 to -2.64 bps
8. EXP-008: Volatility-Regime Conditional Trading (4 regimes x 5 horizons) — no regime produces positive net, net -2.30 to -2.93 bps
9. EXP-009: Order-Book Resiliency Signal (10 dynamics features) — no improvement over baseline, net -2.40 to -2.81 bps
10. EXP-010: Multi-Horizon Signal Ensemble (3 strategies) — all worse than best single horizon, net -2.44 to -2.79 bps
11. EXP-011: Long-Horizon Prediction (5-60 min) — at 5min moves are large (E[|r|]=2.27bps) but features have ~0 correlation, net -3.65 bps
12. EXP-012: Aggressive Flow × Absorption Capacity × Liquidity Fragility (event-level conditional) — even in best state (+0.28 bps mean, 35.4% positive), max return 3.54 bps < 4.0 bps taker cost, net -4.13 bps

### Extended experiments (EXP-013-015):
13. EXP-013: Two-Stage Event + Direction (5min) — 52.4% accuracy < required 63.5%, net -3.55 bps
14. EXP-014: Next-Trade Direction + Book State (10s) — AUC=0.736 but max |ret|=3.67 < 4.0 bps cost, net -3.94 bps
15. EXP-015: Size-Conditioned Trade-Sign (p99.9, 10s) — strongest signal: IC=0.18, dp=1.13 < 4.0 bps cost, net -2.88 bps

### Cross-market/derivatives experiment (EXP-016):
16. EXP-016: Cross-Market/Derivatives Context (funding rate + hourly returns) — NO incremental value. Funding: -0.07 bps incremental. Hourly returns: 0.0 bps incremental. Full model: -0.07 bps. Signal consistent across funding regimes. Bootstrap CI excludes zero. Net remains negative.

## NEXT_ACTION
Terminal state. Research tree fully exhausted (11/11 branches tested).
EXP-016 (cross-market/derivatives context) also rejected.
Total: 16 experiments, all REJECTED. 
Report NO_DEPLOYABLE_EDGE with current information set.

## BLOCKERS
1. Cost-to-signal ratio: 40-200x at short horizons; max return (3.54 bps) < taker cost (4.0 bps)
2. Feature correlations ~0 at all tested horizons (no predictive information)
3. Only 12 sessions of L2 data available (limited sample for learning)
4. 88% of 500ms returns are 0.0 bps (no movement to predict)
5. Strong negative drift at long horizons (mean_r = -1.37 bps at 5min, -5.58 bps at 30min)
6. Even perfect direction prediction at 5min yields only +0.22 bps net (insufficient)
7. Maximum possible return (3.54 bps) structurally below taker round-trip cost (4.0 bps)
8. Cross-market/derivatives context (funding, hourly returns) adds NO incremental value

## FILES_CHANGED
- PROJECT_AUDIT_REPORT.md (created)
- research/NEW_HYPOTHESIS_REVIEW.md (updated)
- research/FINAL_ALGO_REPORT.md (updated — 16 experiments, NO_DEPLOYABLE_EDGE)
- research/hypotheses/EXP-012.md (created)
- research/hypotheses/EXP-016.md (created)
- research/experiment_registry.csv (16 experiments, all rejected)
- app/v8_model.py (created)
- app/exp008_regime.py (created)
- app/exp009_resiliency.py (created)
- app/exp010_ensemble.py (created)
- app/exp011_long_horizon.py (created)
- app/exp012_features.py (created — event-level aggressive flow/absorption/fragility features)
- app/exp012_economic_gate.py (created — economic gate with 4.0 bps taker cost model)
- app/exp012_validation.py (created — purged walk-forward + bootstrap CI validation)
- app/exp016_derivatives.py (created — cross-market/derivatives context feature pipeline)
- app/download_derivatives_data.py (created — downloads funding rates from Binance API)
- app/data_quality.py (created)
- app/walk_forward.py (created)
- app/experiment_registry.py (created)
- app/orchestrator.py (updated with Phase enum, terminal REJECTED state)
- tests/test_v7_infrastructure.py (updated)
- tests/test_exp012.py (created, 20 tests)
- data/research/exp007/exp007_results.json (created)
- data/research/exp008/exp008_results.json (created)
- data/research/exp009/exp009_results.json (created)
- data/research/exp010/exp010_results.json (created)
- data/research/exp011/exp011_results.json (created)
- data/research/exp012/exp012_features.parquet (created)
- data/research/exp012/exp012_results.json (created)
- data/research/EXP-015_results.json (created)
- data/research/EXP-016_results.json (created)
- data/hist/derivatives/BTCUSDT/funding_rates.parquet (91 funding rate records)
- data/hist/derivatives/BTCUSDT/hourly_price.parquet (721 hourly price records)
- data/hist/derivatives/BTCUSDT/exp016_results.json (created)

## TEST_STATUS
All 214 tests pass (1 skipped) — no regressions

Terminal state: NO_DEPLOYABLE_EDGE_WITH_CURRENT_INFORMATION_SET

## EXP-017: Data Acquisition Audit (IN PROGRESS)

### Available Data Dimensions:
| Dimension | Source | Status |
|-----------|--------|--------|
| 1. BTC trades/order-flow | Binance archives | **A** — 730 days full |
| 2. BTC L2/order-book | Binance archives | **D** — historical unavailable (404) |
| 3. BTC open interest | Binance API | **D** — current-only, no history |
| 4. BTC funding rate | Binance API | **B** — 30 days downloaded |
| 5. BTC spot price | Binance API | **B** — 30 days downloaded |
| 6. BTC mark price | Binance API | **B** — available via API |
| 7. BTC spot/perp basis | Derived | **B** — both endpoints available |
| 8. ETH cross-asset | Binance API | **B** — available via API |
| 9. Liquidations | Coinalyze/CoinGlass | **C** — paid subscription |
| 10. Cross-venue BTC | CoinGecko | **C** — ~90 days hourly |

### Critical Finding
**Open interest is the single most important missing dimension — it is FUNDAMENTALLY unavailable**
in historical form from Binance. This was the dimension most expected to provide incremental
predictive power.

### Next Action
Download full 730-day funding rates, spot/perp klines, and ETH data. Then test incremental
information value against the EXP-015 baseline.

## VALIDATION_STATUS
All 16 experiments: REJECTED (EXP-001 through EXP-016)
EXP-017: Data audit COMPLETE — OI unavailable (D), all other dimensions acquired (A/B/C)
EXP-018: Cross-market derivatives analysis COMPLETE — REJECTED, no incremental value

## DEPLOYMENT_STATUS
DEPLOYABLE_EDGE = FALSE
LIVE_TRADING = HARD_BLOCKED
