# MASTER PROJECT FORENSIC AUDIT

**Date:** 2026-08-30
**Auditor:** Kilo (read-only forensic audit)
**Authority:** MASTER_GOVERNANCE_PROTOCOL.md (commit `1f9a667`)
**Scope:** Complete repository inventory, git reconstruction, scientific status, deployability assessment

---

## A. COMPLETE REPOSITORY INVENTORY

### A1. Top-Level Files (84 items)

| Category | Count | Key Files |
|----------|-------|-----------|
| Governance | 1 | `MASTER_GOVERNANCE_PROTOCOL.md` (31.6 KB) |
| V5 Baseline | 4 | `V5_BASELINE.md`, `FROZEN_BASELINE.md`, `PHASE1_BASELINE.md`, `MODEL_SPECIFICATION.md` |
| V6 Research | 12 | `V6_RESEARCH_SPEC_FROZEN.md`, `V6_RESEARCH_SPEC.md`, `V6_RESEARCH_PLAN.md`, `V6_FINAL_DECISION.md`, `V6_OOS_AUDIT.md`, `V6_EXECUTION_AUDIT.md`, `V6_FEATURE_AUDIT.md`, `V6_BLOCKER_RESOLUTION.md` (in data/research/), plus audit/verification docs |
| V7/V8 | 4 | `V7_RESEARCH_PLAN.md`, `V7_FINAL_DECISION.md`, `V7_DATA_SYNCHRONIZATION_AUDIT.md` |
| Alpha/Phase | 5 | `ALPHA_DISCOVERY_PLAN.md`, `ALPHA_DISCOVERY_RESULTS.md`, `PHASE2_ALPHA_DISCOVERY.md`, `RESEARCH_HYPOTHESES.md` |
| Audit/Status | 15 | `AUDIT_LOG.md`, `PROJECT_STATE.md`, `AUTONOMOUS_STATE.md`, `ECONOMIC_VALIDATION_REPORT.md`, `EXECUTION_ECONOMIC_AUDIT.md`, `HORIZON_ECONOMIC_AUDIT.md`, `FORENSIC_ECONOMIC_DATA_AUDIT.md`, `FORENSIC_REPLICATION_REPORT.md`, `PRODUCTION_AUDIT.md`, `FINAL_DEPLOYMENT_AUDIT.md`, `ORDERFLOW_AUTOTRADER_V2_PRODUCTION_READINESS_AUDIT.md`, `ORDERFLOW_PRODUCTION_PATH_AUDIT.md`, `FINAL_ALGORITHM_STATUS.md`, `PROJECT_AUDIT_REPORT.md`, `INFORMATION_SET_AUDIT.md` |
| Pre-registration | 2 | `PRE_REGISTERED_EXECUTION_HYPOTHESES.md`, `PRE_REGISTERED_HORIZON_HYPOTHESES.md` |
| Research Plans | 2 | `ALPHA_DISCOVERY_PLAN.md`, `ALPHA_DISCOVERY_RESULTS.md` |
| Data Audits | 5 | `CROSS_MARKET_DATA_AUDIT.md`, `DERIVATIVES_INFORMATION_AUDIT.md`, `HIGH_FREQUENCY_DATA_AUDIT.md`, `LIQUIDATION_DATA_AUDIT.md`, `INCREMENTAL_EDGE_AUDIT.md` |
| Production Code | 12 | `backtest_production.py`, `calibrate_v5_model.py`, `calibrate_signal_to_return.py`, `paper_validation.py`, `paper_validation_final.py`, `run_paper_simulation.py`, `execution_audit.py`, `horizon_audit.py`, `horizon_control.py`, `phase2_reconciliation.py`, `phase4_oos_validation.py`, `alpha_discovery.py` |
| Config/Infra | 6 | `README.md`, `requirements.txt`, `.env`, `.env.example`, `.gitignore`, `fix_l2_sync.py` |
| Temp/Scratch | 6 | `tmp_audit_and_revalidate.py`, `tmp_revalidate_v3.py`, `tmp_revalidate_v5.py`, `tmp_tier_a.py`, `validate_production_signal.py`, `production_signal_identity_check.py` |

### A2. Directory Structure

| Directory | Contents |
|-----------|----------|
| `app/` | 108 Python modules (production + research + experiments) |
| `data/hist/` | 33 GB — archives, normalized parquet, research outputs, replay |
| `data/live/` | 448 MB — live WebSocket sessions (v2–v5) |
| `data/research/` | 161 MB — all research outputs (v5–v8, experiments) |
| `data/paper_simulation/` | 60 KB — paper trading signals |
| `data/paper_validation/` | 116 KB — validation signals |
| `tests/` | 33 test files (221 tests, 220 pass) |
| `docs/` | 2 files: `BUILD_GATES.md`, `HISTORICAL_DATA.md` |
| `scripts/` | 1 file: `v5_walkforward.py` |
| `research/` | 15 markdown files + 6 subdirectories (hypotheses, experiments, baselines, v7, v5) |

### A3. App Module Inventory (by version)

| Version | Modules | Purpose |
|---------|---------|---------|
| Core | `config.py`, `main.py`, `orchestrator.py`, `binance_feed.py`, `orderbook.py`, `models.py`, `events.py`, `journal.py` | Infrastructure |
| Features | `features.py` | Order-flow feature engine (OFI, CVD, imbalance, etc.) |
| Signal | `signal.py`, `signal_decision.py`, `decision.py` | Signal generation + decision |
| Cost | `v2_cost_gate.py`, `v3_cost.py`, `v5_cost.py`, `v6_cost.py`, `cost_calibrate.py`, `cost_sampler.py` | Execution cost models |
| Execution | `execution.py`, `paper_runtime.py`, `reconciliation.py`, `risk.py`, `fillmodel.py`, `integrity_gate.py` | Trade execution + risk |
| Replay | `replay.py`, `l2_replay.py`, `l2_collector.py`, `l2_integrity.py` | Deterministic replay |
| V5 | `v5_model.py`, `v5_features.py`, `v5_calibration.py`, `v5_validation.py`, `v5_manifest.py`, `v5_economic_report.py`, `v5_run.py`, `v5_evidence.py`, `v5_q2_execution_cost.py`, `v5_replay.py` | Frozen baseline system |
| V6 | `v6_features.py`, `v6_model.py`, `v6_validation.py`, `v6_cost.py`, `v6_execution.py`, `v6_research.py`, `v6_run.py`, `v6_verdict.py`, `v6_comprehensive_validation.py`, `v6_forensic_validation.py`, `v6_microstructure.py`, `v6_phase7.py`, `v6_replication.py`, `v6_reports.py`, `v6_execution_router.py` | Liquidity provision research |
| V7 | `v7_eligibility.py`, `v7_features.py`, `v7_model.py`, `v7_true_features.py` | Cross-market research |
| V8 | `v8_features.py`, `v8_model.py`, `v8_validations.py` | Trade-flow microstructure |
| Experiments | `exp008_regime.py` through `exp018_download.py` (11 modules) | Hypothesis experiments |
| Research (hist/) | `research.py`, `backfill.py`, `audit.py`, `availability.py`, `cond.py`, `costmodel.py`, `economic_gate.py`, `exec.py`, `execution_calibrator.py`, `execution_cost_model.py`, `execution_report.py`, `fill_calib.py`, `integrity.py`, `oos_decomp.py`, `oos_test.py`, `quality.py`, `replay.py`, `report.py`, `sources.py` | Historical research pipeline |
| Walk-forward | `walk_forward.py` | Cross-version walk-forward |

---

## B. GIT HISTORY RECONSTRUCTION

### B1. Commit Timeline (newest first)

| Commit | Date | Message | Scientific Content |
|--------|------|---------|-------------------|
| `1f9a667` | 2026-08-30 | Add permanent project governance protocol | Governance only |
| `01e26ec` | 2026-08-29 | Add V6_BLOCKER_RESOLUTION.md; update V6_RESEARCH_SPEC_FROZEN.md with 6 post-freeze corrections | V6 corrections |
| `6f4a4b3` | 2026-08-29 | V6 research specification: liquidity provision hypothesis | V6 spec creation |
| `2c8301a` | 2026-08-28 | V5 walk-forward: reproducible evaluation script and results | V5 evidence |
| `f9ffc41` | 2026-08-27 | V5 frozen baseline: authoritative reference table | V5 freeze |
| `bf44c6a` | 2026-08-27 | gitignore: exclude live/runtime simulation outputs | Config only |
| `370f647` | 2026-08-27 | Validation audit Phases 1-4: V5 500ms taker rejected economically | V5 audit |
| `b528af8` | 2026-08-27 | Initial research and V8 trading system source | Initial commit |

### B2. Branch State

- **Active branch:** `main`
- **Remote:** `origin/main` (https://github.com/yogeshnamdhari-commits/binance_orderflow_autotrader_v2.git)
- **Ahead of remote:** 7 commits (unpushed)
- **Working tree:** Clean
- **No uncommitted changes**

### B3. Git Forensic Findings

1. All V5 core files committed in `b528af8` and never modified since
2. V5 freeze manifest timestamp (2026-08-18) predates initial commit (2026-08-27) — internally consistent because files unchanged between freeze and commit
3. No force-pushes, no rebases, no history rewriting
4. No unexpected commits or unauthorized changes

---

## C. CURRENT ARCHITECTURE

### C1. Production Path (Live)

```
main.py
  → BinanceMarketFeed (WebSocket: depth@100ms, @trade, @bookTicker)
  → LocalOrderBook (apply, integrity checks, gap/stale detection)
  → OrderFlowEngine (OFI, CVD, imbalance, spread, depth features)
  → SignalEngine (heuristic: buy/sell >= 0.9 threshold)
  → IntegrityGate (book sync validation)
  → TradeOrchestrator (GOVERNANCE BLOCK: always allowed=False)
  → RiskEngine (position sizing)
  → PaperExecution (paper-only, no live orders)
  → Journal (JSONL)
```

**Critical finding:** The frozen V5 ridge model (`v5_model.json`) is NOT wired into `main.py`. The live path uses `SignalEngine` heuristic, not the validated V5 model. `TradeOrchestrator` hard-blocks all live trading.

### C2. Research Path (Frozen V5)

```
v5_run.py (orchestrator)
  → v5_replay.py (raw → derived, integrity-gated)
  → v5_features.py (17 causal order-flow features)
  → v5_model.py (Ridge α=0.05, closed-form, train-only fit)
  → v5_validation.py (OOS scoreboard, per-session)
  → v5_cost.py (measured gate: 4.6658 bps taker, 2.0 bps maker)
  → v5_economic_report.py (robustness cells, cost sensitivity)
  → v5_manifest.py (freeze verification, SHA256 hashes)
```

### C3. Research Path (V6)

```
v6_comprehensive_validation.py (500 lines — primary)
  → v6_features.py (38 features in 13 groups)
  → v6_model.py (MLPRegressor 32×16, but saved model is Ridge)
  → v6_validation.py (walk-forward, execution simulation)
  → v6_cost.py (contemporary cost distribution)
  → v6_execution.py (maker/taker/hybrid router)
  → v6_reports.py (13 report files)
```

**Finding:** V6 code diverges significantly from frozen spec. Spec says maker limit-order strategy at {1s, 5s, 30s}; code implements taker-directional at {250ms, 500ms, 1000ms}.

---

## D. V5 STATUS

### D1. Specification

| Property | Value |
|----------|-------|
| Model type | Ridge regression (closed-form, analytical) |
| Alpha | 0.05 |
| Features | 17 causal order-flow features |
| Primary horizon | 500 ms |
| Train/Val/OOS split | 70/15/15 chronological (18145/3888/3889 rows) |
| Standardization | z-score using train-slice μ/σ |
| Fit convention | ONCE on train slice; coefficients frozen |
| R² train (500ms) | 0.260989 |
| Freeze timestamp | 2026-08-18T21:11:35 |

### D2. Feature List (17)

`ofi_l1`, `ofi_norm_l1`, `qi_l1`, `di_l5`, `di_l10`, `mpd_bps`, `spread_bps`, `bid_cancel_bps`, `ask_add_bps`, `cancel_pressure`, `tfi_500`, `liq_depletion`, `log_depth1`, `log_depth5`, `log_event_rate`, `depth_slope_bps`, `vol_500`

### D3. Frozen OOS Results (2 sessions)

| Metric | Value |
|--------|-------|
| OOS rows | 3,889 |
| Executed trades | 0 |
| Gross expectancy | +0.0641 bps |
| Gross std | 0.3781 bps |
| **Verdict** | **CONDITIONAL PASS (inconclusive)** |

**Why inconclusive:** No prediction exceeded the 4.6658 bps gate, so zero trades were executed. The verdict engine correctly flagged: "directional sample too small: long=0 short=0 (need >=200 each)."

### D4. V5.1 Evidence Expansion (15 walk-forward sessions)

| Metric | Value |
|--------|-------|
| Walk-forward sessions | 15 |
| Mean gross | +0.078 bps |
| Median correlation | 0.140 |
| Max observed move | 4.29 bps |
| Sessions with corr > 0 | 10/13 |
| **Verdict** | **FAIL ECONOMICALLY** |

### D5. V5 Integrity Assessment

| Check | Result |
|-------|--------|
| Core files unchanged since commit | YES |
| Freeze manifest valid | YES |
| V5_BASELINE.md hash | `9be63b4ec2f9bb5b198e8fcd27c2072a` |
| Live trading hard-blocked | YES (`V5_BASELINE_NO_LIVE_TRADE = True`) |
| NO_DEPLOYABLE_EDGE conclusion | Economically valid (but derived from V5.1, not frozen OOS) |

---

## E. V6 STATUS AND EXACT FALSIFICATION EVIDENCE

### E1. Hypothesis

**H1:** There exist identifiable states of the limit order book where the expected net executable return from providing liquidity at the best bid or ask is strictly positive after all costs.

**H0 (Null):** For all identifiable states, E[net_return | s] ≤ 0.

### E2. Falsification Evidence

#### E2a. Economic Gate (all 16 scenarios = NO_TRADE)

| Horizon | Gross Edge (bps) | Maker Cost (bps) | Net (bps) | Cost/Gross |
|---------|-----------------|------------------|-----------|------------|
| 1s | 0.159 | 2.732 | -2.573 | 17.2× |
| 5s | 0.199 | 2.732 | -2.533 | 13.7× |
| 30s | 0.280 | 2.996 | -2.716 | 10.7× |

#### E2b. Feature-Level Results (7 features)

| Feature | Gross (bps) | p-value | Net Maker (bps) | Sessions + |
|---------|-------------|---------|-----------------|------------|
| vamp_deviation | 0.120 | <0.0001 | -2.438 | 8/9 |
| absorption_ratio | 0.002 | 0.662 | -2.556 | 4/9 |
| resiliency | 0.003 | 0.087 | -2.555 | 4/9 |
| convexity | 0.001 | 0.848 | -2.557 | 4/9 |
| flow_persistence | -0.005 | 0.176 | -2.563 | 5/9 |
| spread_regime | 0.001 | 0.771 | -2.557 | 4/9 |
| flow_pressure | 0.002 | 0.662 | -2.556 | 4/9 |

Bonferroni α = 0.00714. All net expectancies deeply negative.

#### E2c. Walk-Forward (vamp_deviation)

| Split | N | Gross | Net Maker |
|-------|---|-------|-----------|
| 1 | 9,168 | 0.054 | -1.946 |
| 2 | 9,429 | 0.095 | -1.905 |
| 3 | 8,161 | 0.043 | -1.957 |
| 4 | 10,893 | 0.159 | -1.841 |

**All walk-forward splits have negative net edge.**

#### E2d. Independent Replication

| Metric | Value |
|--------|-------|
| Untouched sessions | 10 |
| Net (contemporaneous) | **-2.207896 bps** |
| Net HAC p-value | 0.0 |
| **Verdict** | **REPLICATION_FAIL** |

#### E2e. Structural Economic Constraint

- Half-spread: 0.0079 bps
- Maker fee (VIP 0): 2.0 bps round-trip
- **Maker fee alone exceeds best gross edge by 7.1×**
- Even with ZERO adverse selection, ZERO latency, ZERO slippage — the fee cannot be overcome

### E3. V6 Code vs. Spec Discrepancies

| Aspect | Frozen Spec | Actual Code |
|--------|-------------|-------------|
| Strategy type | Maker limit-order provision | Taker directional with cost gate |
| Horizons | {1s, 5s, 30s} | {250ms, 500ms, 1000ms} |
| Features | 10 pre-specified | 38 implemented |
| Net-return terms | 9 (full equation) | 3 (fee + slippage + latency) |
| Deployment gate | 17 criteria | 6 checked |
| Queue model | Explicit Pareto + FIFO | Not implemented |
| 10-stage lifecycle | Specified | Not implemented |

### E4. V6 Verdict

**FALSIFIED** — H1 is rejected. No identifiable state produces positive net executable return after all costs. The economic gap is structural: the maker fee alone (2.0 bps) exceeds the best achievable gross edge (0.280 bps) by 7.1×.

---

## F. EXISTING V7/V8 MATERIAL

### F1. V7: Cross-Market Price Discovery

| Property | Value |
|----------|-------|
| Hypothesis | Cross-venue information predicts Binance BTCUSDT |
| Pre-registered hypotheses | 6 (H1–H6) |
| Status | **D = DATA INSUFFICIENT** |
| Blocker | No cross-venue data (Coinbase, Kraken, Bybit, OKX) |
| Internal test result | NEGATIVE_EDGE across all model variants |
| Best gross (46 features) | 0.045 bps |
| Net maker | -1.955 bps |

### F2. V8: Trade-Flow Microstructure

| Property | Value |
|----------|-------|
| Hypothesis | Trade-flow features from 730-day aggTrades provide incremental edge |
| Features | 12 novel (trade_size_k, inter_arrival_s, flow_accel, etc.) |
| Status | **NOT_READY — REJECTED** |
| Best feature | price_run_bps: 0.464 bps gross |
| Net maker | -2.036 bps |
| Walk-forward | 0/4 windows positive |

### F3. Experiments (EXP-001 through EXP-018)

| ID | Hypothesis | Gross (bps) | Net (bps) | Verdict |
|----|-----------|-------------|-----------|---------|
| EXP-001 | V5 Ridge (17 OFI) | +0.069 | -1.931 | REJECTED |
| EXP-002 | V6 MLP (25 features) | +0.100 | -1.900 | REJECTED |
| EXP-003 | V7 Multi-Level (46) | +0.045 | -1.955 | REJECTED |
| EXP-004 | V7 Purged Validation | -0.003 | -2.003 | REJECTED |
| EXP-005 | V8 Direction-Mag (500ms) | 0.000 | -2.500 | REJECTED |
| EXP-006 | V8 Direction-Mag (30s) | 0.000 | -2.500 | REJECTED |
| EXP-007 | Horizon-Matched Aggregation | -0.137 | -2.637 | REJECTED |
| EXP-008 | Volatility-Regime Conditional | -0.227 | -2.637 | REJECTED |
| EXP-009 | Order-Book Resiliency | +0.096 | -2.404 | REJECTED |
| EXP-010 | Multi-Horizon Ensemble | -0.294 | -2.770 | REJECTED |
| EXP-011 | Long-Horizon (5-60 min) | -1.145 | -3.645 | REJECTED |
| EXP-012 | Flow × Capacity × Fragility | -0.083 | -4.128 | REJECTED |
| EXP-013 | Two-Stage Event + Direction | — | -3.55 | REJECTED |
| EXP-015 | Size-Conditioned Trade-Sign | +1.22 | -2.88 | REJECTED |
| EXP-016 | Cross-Market/Derivatives | +1.22 | -2.88 | REJECTED |
| EXP-017 | Information-Set Audit | N/A | N/A | AUDIT |
| EXP-018 | Cross-Market (730-day) | +1.35 | -2.77 | REJECTED |

**Total experiments: 18+. Terminal state: NO_DEPLOYABLE_EDGE_WITH_CURRENT_INFORMATION_SET.**

---

## G. COMPONENTS THAT ARE COMPLETE AND REUSABLE

| Component | Status | Quality |
|-----------|--------|---------|
| V5 Ridge model + 17 features | Complete, frozen, reproducible | High |
| V5 calibration pipeline | Complete | High |
| V5 freeze manifest + verification | Complete | High |
| V5 walk-forward framework | Complete (15 sessions) | High |
| Order book reconstruction (L2) | Complete, bit-exact replay | High |
| OFI/CVD feature engine | Complete, tested | High |
| Execution cost calibration | Complete (7,279 samples) | High |
| Fill probability calibration | Complete (16 scenarios) | High |
| Economic gate framework | Complete (all 16 scenarios evaluated) | High |
| Binance WebSocket feed | Complete, reconnect logic | High |
| Integrity gate (book sync) | Complete, gap/stale detection | High |
| Deterministic replay engine | Complete, session-based | High |
| Test suite (221 tests) | Complete, 220 pass | High |
| Governance protocol | Complete, committed | High |
| Data normalization pipeline | Complete (730 days parquet) | High |
| Research report generation | Complete (13 report types) | High |

---

## H. COMPONENTS THAT ARE INCOMPLETE

| Component | What's Missing |
|-----------|----------------|
| V6 maker-limit-order simulator | Spec defines 10-stage lifecycle, queue model, fill probability — none implemented |
| V6 queue position model | Pareto order-size distribution specified but not coded |
| V6 funding cost accounting | Spec requires FundingPayment + FundingCost terms — not in net-return calculation |
| V6 17-criterion deployment gate | Only 6 criteria checked in code |
| V7 cross-venue data ingestion | No Coinbase/Kraken/Bybit connectors |
| V8 trade-flow feature pipeline | Features defined but walk-forward fails |
| Live trading path wiring | V5 model not connected to main.py |
| Binned calibration | Module exists but never called by orchestrator |

---

## I. BROKEN/MISSING COMPONENTS

| Component | Issue | Severity |
|-----------|-------|----------|
| `v6_run.py` orchestrator | Imports non-existent functions (`build_features`, `calibrate`, `validate`) | Medium |
| `v6_verdict.py` | Uses hardcoded placeholder values (V5=0.07, V6=0.08), not actual results | Medium |
| V5.1 post-freeze code | `v5_calibration.py`, `v5_evidence.py`, `v5_q2_execution_cost.py` not in freeze manifest | Low |
| `v5_manifest.py` | References `app/v5_labels.py` which doesn't exist | Low |
| `v5_validation.py:58` | `np.where(executed, 0.0, 0.0)` — both branches identical | Low |
| `v5_economic_report.py:65` | `oos = df.loc[df.index.isin(df.index)]` — tautology | Low |
| Three V5 baseline numbers | 0.064 (frozen), 0.174 (SignalEngine), 0.041 (DecisionEngine) used inconsistently | Medium |

---

## J. EXISTING TESTS AND THEIR ACTUAL RESULTS

### J1. Test Suite Summary

| Metric | Value |
|--------|-------|
| Total test files | 33 |
| Total tests collected | 221 |
| Passed | 220 |
| Skipped | 1 |
| Failed | 0 |
| Runtime | 43.47s |

### J2. Test Coverage by Module

| Module | Tests | Status |
|--------|-------|--------|
| Core (order book, events) | 5 | PASS |
| Features (OFI, CVD, imbalance) | 4 | PASS |
| Cost calibration | 6 | PASS |
| Decision logic | 6 | PASS |
| Execution | 5 | PASS |
| Fill model | 6 | PASS |
| Feed sync | 2 | PASS |
| L2 replay | 4 | PASS |
| Orchestrator | 2 | PASS |
| Reconciliation | 11 | PASS |
| Replay | 1 | PASS |
| Risk | 7 | PASS |
| Safety block | 4 | PASS |
| V2 OOS | 7 | PASS |
| V2 research | 5 | PASS |
| V3 model | 6 | PASS |
| V4 model | 7 | PASS |
| V5 model | 8 | PASS |
| V5 calibration | 4 (1 skipped) | PASS |
| V5 evidence | 8 | PASS |
| V5 governance | 6 | PASS |
| V5 Q2 execution cost | 18 | PASS |
| V6 model | 10 | PASS |
| V7 infrastructure | 15 | PASS |
| EXP-012 | 20 | PASS |
| EXP-013 | 9 | PASS |
| Condition | 10 | PASS |
| Feature parity | 2 | PASS |
| Hardening | 17 | PASS |
| Historical data | 5 | PASS |
| Integration | 4 | PASS |
| Research pipeline | 1 | PASS |

---

## K. DATA AVAILABILITY AND QUALITY

### K1. Data Inventory

| Directory | Size | Contents |
|-----------|------|----------|
| `data/hist/normalized/BTCUSDT/aggTrades/` | 20 GB | 730 parquet files (2024-08-16 to 2026-08-15) |
| `data/hist/archives/BTCUSDT/aggTrades/` | 13 GB | 730 ZIP files (SHA256-verified) |
| `data/hist/raw/BTCUSDT/aggTrades/` | 384 MB | 6 CSV files (partial, Sep 2024 only) |
| `data/hist/derivatives/BTCUSDT/` | 17 MB | Hourly spot/perp, funding rates, price |
| `data/hist/research/` | 5.9 MB | Calibration, economic gate, fill calib |
| `data/hist/replay/` | 12 KB | Replay journal |
| `data/live/` | 448 MB | Live WebSocket sessions (v2–v5) |
| `data/research/` | 161 MB | All research outputs (v5–v8, experiments) |

### K2. Data Quality Assessment

| Dimension | Status | Details |
|-----------|--------|---------|
| aggTrades coverage | ✅ COMPLETE | 730/730 days, zero gaps, SHA256-verified |
| Normalization | ✅ COMPLETE | 730 individual parquet files |
| Execution calibration | ✅ COMPLETE | 7,279 live samples, ~2 hours |
| Fill calibration | ✅ COMPLETE | 16 scenarios (4 deltas × 4 horizons) |
| Economic gate | ✅ COMPLETE | 16 maker/taker decisions, all NO_TRADE |
| Historical L2 order book | ❌ UNAVAILABLE | Binance does not publish historical L2 |
| Cross-venue data | ❌ UNAVAILABLE | No Coinbase/Kraken/Bybit data |
| Liquidation feeds | ❌ UNAVAILABLE | Paid subscription only |
| Open interest history | ❌ UNAVAILABLE | Current-only API, no historical endpoint |
| Raw CSV download | ⚠️ INCOMPLETE | Only 6 of 730 days downloaded |

### K3. Data Consistency

All model versions (v5–v8) share identical train/validation/OOS splits (18145/3888/3889 rows) with timestamp boundaries ~1787080068–1787082921, confirming a single frozen dataset was used across all experiments.

---

## L. EXECUTION-COST MODEL

### L1. Cost Components (measured)

| Component | Value | Source |
|-----------|-------|--------|
| Taker fee (round-trip) | 4.0 bps | `execution_calibration.json` |
| Maker fee (round-trip) | 2.0 bps | `execution_calibration.json` |
| Spread (p90) | 0.0158 bps | `execution_calibration.json` |
| Slippage (p90, 1K notional) | 0.0079 bps | `execution_calibration.json` |
| Impact allowance | 0.1 bps | `v3_cost.py` |
| Latency cost | 0.05 bps | `v3_cost.py` |
| Safety margin | 0.5 bps | `v3_cost.py` |
| **Total taker gate** | **4.6658 bps** | Computed |
| **Total maker cost (30s)** | **2.996 bps** | `economic_gate.json` |

### L2. Binance Fee Schedule (verified)

| VIP Tier | Maker | Taker |
|----------|-------|-------|
| Regular (0) | 0.02% (2 bps) | 0.05% (5 bps) |
| VIP 4 | 0.01% (1 bps) | 0.03% (3 bps) |
| VIP 9 | -0.005% (rebate) | 0.017% (1.7 bps) |

**Note:** Project calibration uses maker = 1.0 bps/side, which corresponds to VIP 4, not VIP 0. True VIP 0 maker = 2 bps/side = 4 bps round-trip (even more unfavorable).

### L3. Funding Rate Data

| Metric | Value |
|--------|-------|
| Records | 2,214 |
| Coverage | 730 days |
| Mean | 0.45 bps/8h |
| Range | -1.52 to +7.24 bps/8h |
| Per-trade cost at 30s | ~0.0005 bps (negligible) |

---

## M. BACKTESTING METHODOLOGY

### M1. Data Splitting

| Split | Method | Buffer |
|-------|--------|--------|
| Train/Val/OOS | Chronological 70/15/15 by timestamp quantile | 10-minute purge gap |
| Walk-forward | Expanding window, session-based | No temporal overlap |

### M2. Leakage Controls

| Control | Implementation |
|---------|---------------|
| Chronological ordering | Preserved (no shuffling) |
| Feature timestamps | All features use strictly-earlier timestamps |
| Label construction | Post-fill price measured from first event after fill |
| Standardization | Mean/sd computed on train slice only |
| Purge buffer | 10-minute gap between train and OOS |
| Embargo | No overlapping events between splits |

### M3. Statistical Tests

| Test | Usage |
|------|-------|
| HAC-robust t-test | Net expectancy significance |
| Bonferroni correction | Multiple-testing across 3 horizons (α = 0.05/3) |
| Permutation control | Feature significance vs null |
| Bootstrap CI | 95% confidence on gross/net expectancy |
| Walk-forward validation | 15 sessions (V5.1) |

---

## N. WALK-FORWARD / OOS METHODOLOGY

### N1. V5 Walk-Forward Design

1. Train on sessions 1–12
2. Validate on session 13 (threshold calibration only)
3. OOS test on sessions 14–15
4. Expand training window, repeat
5. Aggregate across all OOS folds

### N2. OOS Results Summary

| Version | Sessions | Mean Gross | Net Maker | Pass Gate |
|---------|----------|-----------|-----------|-----------|
| V5 frozen | 2 | +0.064 bps | 0.0 (inconclusive) | CONDITIONAL PASS |
| V5.1 | 15 | +0.078 bps | -4.58 bps | FAIL |
| V6 | 9 | +0.120 bps | -2.44 bps | FAIL |
| V7 | proxy | +0.045 bps | -1.96 bps | FAIL |
| V8 | 4 WF | +0.464 bps | -2.04 bps | FAIL |

---

## O. LEAKAGE CONTROLS

### O1. Documented Controls

| Control | Status |
|---------|--------|
| Chronological splits (no shuffling) | ✅ Implemented |
| Purge buffer (10-minute gap) | ✅ Implemented |
| Embargo (no overlapping events) | ✅ Implemented |
| Feature timestamps (strictly-earlier) | ✅ Implemented |
| Standardization (train-slice μ/σ) | ✅ Implemented |
| Walk-forward (expanding window) | ✅ Implemented |
| Permutation control | ✅ Implemented |
| Bonferroni correction | ✅ Implemented |

### O2. Leakage Risk Assessment

| Risk | Status |
|------|--------|
| Future data leakage | ✅ None detected |
| Train/OOS contamination | ✅ None detected |
| Feature look-ahead | ✅ None detected |
| Selection bias (horizon) | ⚠️ 30s horizon selected from performance (DATA-DRIVEN flag added) |
| Selection bias (threshold) | ⚠️ 0.5 bps threshold repurposed from safety margin |

---

## P. RISK CONTROLS

### P1. Governance-Level Controls

| Control | Implementation |
|---------|---------------|
| `V5_BASELINE_NO_LIVE_TRADE = True` | Hard-coded in `config.py`, `orchestrator.py`, `main.py` |
| TradeOrchestrator | Always returns `allowed: False` |
| PaperExecution | Paper-only, no live orders |
| Safety block (`test_safety_block.py`) | 4 tests verify hard block |

### P2. Research-Level Controls

| Control | Implementation |
|---------|---------------|
| Economic gate | Gross must exceed cost before trade |
| Multiple-testing correction | Bonferroni across horizons |
| HAC-robust inference | Heteroskedasticity-autocorrelation robust |
| Permutation control | Features tested vs null distribution |
| Walk-forward validation | Out-of-sample across sessions |

---

## Q. DEPLOYMENT READINESS

### Q1. Build Gates (from `docs/BUILD_GATES.md`)

| Gate | Status | Evidence |
|------|--------|----------|
| 1. Data | ✅ PASS | 730 days, verified, normalized |
| 2. Research | ⚠️ PARTIAL | Signal exists but too small |
| 3. Strategy | ❌ FAIL | No strategy passes economic gate |
| 4. Backtest | ✅ PASS | Walk-forward implemented, no leakage |
| 5. Execution | ⚠️ PARTIAL | Cost model calibrated, but no edge to execute |
| 6. Deployment | ❌ FAIL | Live trading hard-blocked, no deployable edge |

### Q2. Deployment Verdict

**NOT READY.** No strategy (V5, V6, V7, V8, or any experiment) produces positive net expectancy after realistic execution costs. Live trading is correctly hard-blocked at the code level.

---

## R. EXACT BLOCKERS

### R1. Critical Blockers

| # | Blocker | Permanence |
|---|---------|------------|
| 1 | **Economic gap: cost-to-signal ratio 7–17×** | Structural — requires 7× signal improvement or 7× fee reduction |
| 2 | **No deployable edge across 18+ experiments** | Empirical — all hypotheses tested and rejected |

### R2. High Blockers

| # | Blocker | Impact |
|---|---------|--------|
| 1 | Historical L2 order book unavailable | Cannot backtest queue/fill features historically |
| 2 | Cross-venue data unavailable | V7 hypothesis untestable |
| 3 | Only 2 OOS sessions in frozen V5 | Insufficient for session-stratification criterion |
| 4 | V6 code diverges from frozen spec | Implementation does not match specification |

### R3. Medium Blockers

| # | Blocker | Impact |
|---|---------|--------|
| 1 | 30s horizon selected from performance | DATA-DRIVEN selection, not ex-ante |
| 2 | V5.1 post-freeze code not in freeze manifest | Governance gap |
| 3 | Inconsistent V5 baseline numbers (0.064/0.174/0.041) | Documentation accuracy |
| 4 | V6 queue model not implemented | Spec not fully coded |

### R4. Low Blockers

| # | Blocker | Impact |
|---|---------|--------|
| 1 | `v6_run.py` orchestrator broken (bad imports) | Non-functional |
| 2 | `v6_verdict.py` uses hardcoded placeholders | Non-functional |
| 3 | `v5_calibration.py` never called by orchestrator | Dead code |
| 4 | Minor code quality issues (dead code, tautologies) | Cosmetic |

---

## S. MINIMUM SCIENTIFICALLY VALID PATH TO A DEPLOYABLE ALGORITHM

### S1. Honest Assessment

Given the current state:
- 18+ experiments conducted across V5–V8
- All produce negative net expectancy
- Cost-to-signal ratio is 7–17× (structural)
- Maximum observed return (3.54 bps) < taker cost (4.0 bps)
- No information source (order flow, derivatives, cross-market, trade flow) provides incremental edge

**There is currently no scientifically valid path to a deployable algorithm on BTCUSDT with the available information set.**

### S2. What Would Be Required

| Requirement | Feasibility |
|-------------|-------------|
| Signal improvement of 7–17× (gross edge from 0.28 bps to >3.0 bps) | Would require fundamentally different information source |
| Access to VIP 9 fee status ($4B 30-day volume) | Institution-only |
| Historical L2 order book data | Not available from Binance; would require live accumulation over months |
| Cross-venue data (Coinbase, Kraken) | Available but expensive; V7 hypothesis would need redesign |
| Alternative data (liquidations, on-chain, sentiment) | Partially available; untested |

### S3. If a New Hypothesis (V7/V8/V9) Is Pursued

The correct sequence per MASTER_GOVERNANCE_PROTOCOL.md:

1. **Literature/economic mechanism research** — identify a genuine edge source not yet tested
2. **Independent hypothesis specification** — falsifiable, pre-registered
3. **Data feasibility confirmation** — required data actually obtainable
4. **Pre-register** horizon, execution mechanism, costs, thresholds
5. **Implement research code** (read-only audit layer)
6. **OOS validation** (≥3 sessions, walk-forward, Bonferroni)
7. **Economic gate** (gross > all costs)
8. **Independent replication** (untouched data)
9. **Only then** consider implementation

### S4. What NOT to Do

- Do not optimize V6 parameters
- Do not change thresholds to manufacture profitability
- Do not select horizons from performance
- Do not merge V5/V6 into a hybrid
- Do not reopen V5
- Do not implement without passing all gates
- Do not turn V6 into "V6.1"

---

## PROJECT STATUS

| Component | Status |
|-----------|--------|
| **V5** | 🔒 FROZEN negative control. Ridge regression, 17 OFI features, 500ms horizon. Gross +0.064–+0.085 bps. Net -1.83 to -4.58 bps. Verdict: NO_DEPLOYABLE_EDGE (economically infeasible). |
| **V6** | 🔒 FROZEN + **FALSIFIED**. Liquidity-provision hypothesis rejected. Best gross 0.280 bps vs maker cost 2.0+ bps. Cost-to-signal ratio 7–17×. Independent replication: REPLICATION_FAIL. |
| **V7/V8** | 🔒 FROZEN + REJECTED. V7: data insufficient (no cross-venue). V8: best gross 0.464 bps, net -2.04 bps. All 18+ experiments produce negative net expectancy. |
| **CURRENT DEPLOYABILITY** | 🚫 **NOT DEPLOYABLE.** Live trading hard-blocked at code level. No strategy passes economic gate. |
| **CRITICAL BLOCKERS** | 1. Structural cost-to-signal gap (7–17×). 2. No information source produces deployable edge. |
| **NEXT SCIENTIFICALLY VALID ACTION** | STOP. No valid path to deployment with current information set. A new hypothesis (V9) would require: (a) genuinely new economic mechanism, (b) data feasibility confirmation, (c) independent specification, (d) full research cycle from scratch. |

---

## APPENDIX: KEY DOCUMENT CROSS-REFERENCES

| Document | Location | Purpose |
|----------|----------|---------|
| MASTER_GOVERNANCE_PROTOCOL.md | Root | Permanent governance constitution |
| V5_BASELINE.md | Root | Frozen baseline reference |
| V6_RESEARCH_SPEC_FROZEN.md | Root | V6 frozen specification (496 lines) |
| V6_BLOCKER_RESOLUTION.md | data/research/ | Blocker resolution report (1340 lines) |
| V6_SPEC_VERIFICATION.md | data/research/ | Independent verification (219 lines) |
| V6_FINAL_DECISION.md | Root | V6 verdict: NO ROBUST INCREMENTAL EDGE |
| V7_RESEARCH_PLAN.md | Root | V7 research plan |
| V7_FINAL_DECISION.md | Root | V7 verdict: DATA INSUFFICIENT |
| PROJECT_STATE.md | Root | Comprehensive state summary |
| AUDIT_LOG.md | Root | Phased audit history |
| ECONOMIC_VALIDATION_REPORT.md | Root | Economic audit |
| EXECUTION_ECONOMIC_AUDIT.md | Root | Execution audit |
| HORIZON_ECONOMIC_AUDIT.md | Root | Horizon analysis |
| FORENSIC_REPLICATION_REPORT.md | Root | Replication audit |
| PRODUCTION_AUDIT.md | Root | Production readiness |
| FINAL_DEPLOYMENT_AUDIT.md | Root | Deployment audit |
| ORDERFLOW_AUTOTRADER_V2_PRODUCTION_READINESS_AUDIT.md | Root | Production readiness (846 lines) |

---

**Audit completed:** 2026-08-30
**Auditor:** Kilo (read-only)
**Files modified:** NONE (audit-only task)
**Repository state:** Clean, HEAD `1f9a667`
**V5 integrity:** Confirmed frozen
**V6 integrity:** Confirmed falsified
**Implementation authorization:** NOT AUTHORIZED

---

*This audit is the authoritative current project state document. It supersedes all prior status documents where contradictions exist.*
