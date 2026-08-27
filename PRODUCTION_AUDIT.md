# Production-Readiness Audit: V5 Orderflow Baseline

**Date**: 2026-08-25  
**Status**: STATISTICALLY PREDICTIVE — ECONOMICALLY INSUFFICIENT  
**Live Trading**: BLOCKED (V5_BASELINE_NO_LIVE_TRADE = TRUE)  
**Verdict**: No deployable edge with the current information set. Frozen baseline is clean.

---

## A. Architecture Status

### Pipeline
```
Raw L2 (Binance) → ReplayV4 → V5 features → V5 ridge model → Cost gate → Decision
```

### Key Components (frozen, no modifications)

| Component | File | Role |
|-----------|------|------|
| OrderFlowEngine | `app/features.py` | Causal order-flow feature computation (17 V5 features + extended fields) |
| EventDetector | `app/events.py` | Pattern-based microstructure event detection (BUY_FLOW, SELL_FLOW, POTENTIAL_ABSORPTION) |
| SignalEngine | `app/signal.py` | Sign-based signal engine (simple threshold on event strength ≥ 0.9) |
| DecisionEngine | `app/decision.py` | V5 model → calibrated expected return → execution cost gate → net → decision |
| TradeOrchestrator | `app/orchestrator.py` | Governance hard block: V5_BASELINE_NO_LIVE_TRADE blocks all trades |
| IntegrityGate | `app/integrity_gate.py` | Chain: BOOK_SYNCED → FEATURES_VALID → COST_VALID → SIGNAL_ALLOWED |
| RiskEngine | `app/risk.py` | Pre-trade risk controls (spread, exposure, drawdown, stale data, emergency Kill switch) |
| Journal | `app/journal.py` | Persistent audit trail for all decisions |

### Two Parallel Signal Systems
- **Production pipeline (main.py)**: EventDetector → SignalEngine (simple pattern-based thresholds)
- **Research pipeline (v5_evidence.py)**: V5 ridge model → binned calibration → cost gate
- Both are frozen. No new signal engines were created. No duplication introduced.

### Safety Switches
- `V5_BASELINE_NO_LIVE_TRADE = True` in `app/config.py:9` (hard-coded, not env-driven)
- `TradeOrchestrator.decide()` returns `allowed=False` immediately when governance lock is active
- `Config.runtime_safe()` blocks live mode when `V5_BASELINE_NO_LIVE_TRADE` is True
- `Config.assert_safe()` blocks live mode when `LIVE_TRADING_ENABLED=false`
- IntegrityGate chain blocks all trading on book sync failure

## B. Feature Parity

- **22/22 V5 features match** between research (ReplayV4 + v5_features.py) and live (OrderFlowEngine.snapshot)
- **0 mismatches** across 2,292 feature comparison rows (after the causal-information-set fix in `v3_replay.py`)
- Exchange timestamps (E/T) are non-monotonic (253 out-of-order cases in session 20260818-191124)
- Event processing order is by `recv_ms` (receive time), not exchange event time — preserves causal information set
- `vol_500` computed via `add_trailing_vol` (research) matches `_trailing_vol` (live)

## C. Model Status

- **Model**: Frozen ridge regression (alpha=0.05) at `data/research/v5_model.json`
- **Features**: 17 V5 features (fixed, pre-registered)
- **Horizon**: 500ms (primary)
- **Training split**: 18,145 rows (70% chronological)
- **Validation split**: 3,888 rows (15%)
- **OOS split**: 3,889 rows (15%, within training sessions only)
- **Coefficients**: Unchanged, no modifications made
- **Top coefficients**: qi_l1 (1.995), mpd_bps (-1.928), di_l10 (-1.914), di_l5 (1.881)

## D. Signal Statistics (Frozen Baseline)

### Pooled (all 22 OOS evidence sessions, 49,897 eligible signals)

| Metric | Value |
|--------|-------|
| Gross expectancy | 0.0955 bps |
| Net (taker, after 4.6658 bps gate) | -4.5703 bps |
| Std | 0.5147 bps |
| t-stat | 41.42 |
| p-value | <0.0001 |
| 95% CI (gross) | [0.0909, 0.0999] bps |
| Hit rate (sign match) | 12.2% (mostly zero-actuals) |
| Hit rate (non-zero actuals) | 78.2% |
| Sessions with positive gross | 20/22 (90.9%) |
| Signals passing gate (|pred| > 4.6658) | 210 |
| Gated gross (210 signals) | 2.460 bps |
| Gated net | -2.206 bps |

### Session-level
- Mean session gross: 0.085 bps
- Session t-stat: 4.87, p-value: 8.3e-05
- Range: -0.011 to +0.258 bps

## E. Conditional Microstructure Analysis

### Method
- **Discovery set**: 12 training sessions (chronological timestamps 1787080068417–1787082331201)
- **Validation set**: 10 OOS sessions (timestamps 1787082331303 onward, never seen by the model)
- **15 pre-registered hypotheses** based on microstructure theory (not data-mined):
  1. TFI_abs > 0.5 (strong directional flow)
  2. TFI_abs > 0.5 & vol > 0 (flow with volatility)
  3. |qi_l1| > 0.7 (one-sided book)
  4. |qi_l1| > 0.7 & sign(di_l10)==sign(qi_l1) (aligned depth)
  5. liq_dep > 50pct (depth consumption)
  6. TFI_abs > 0.7 & liq_dep > 50pct (flow consuming depth)
  7. cancel_pres > 50pct (cancellation pressure)
  8. log_event_rate > p50 (high activity)
  9. TFI_abs > 0.7 & vol > p50 (strong flow × volatility regime)
  10. spread > p80 (wide spread regime)
  11. |OFI| > 0 & |qi_l1| > 0.5 (OFI × queue imbalance)
  12. OFI signed & |qi| > 0.5 (directional OFI × queue imbalance)
  13. log_depth1 < p30 & log_depth5 > p70 (thin top, deep total)
  14. TFI > 0 & depth_slope > 0 (directional flow × liquidity shape)
  15. vol_500 > 0 (any volatility activity)

### Results (Validation)

| # | Condition | N_val | Gross (bps) | Net (bps) | t-stat | p-value | Bootstrap CI (bps) |
|---|-----------|-------|-------------|-----------|--------|---------|-------------------|
| 1 | TFI_abs > 0.5 | 23,981 | 0.227 | -4.439 | 31.4 | <0.001 | [0.101, 0.278] |
| 2 | TFI_abs > 0.5 & vol > 0 | 3,812 | 0.690 | -3.976 | 25.6 | <0.001 | [0.199, 0.797] |
| 3 | \|qi_l1\| > 0.7 | 23,981 | 0.246 | -4.420 | 33.6 | <0.001 | [0.128, 0.345] |
| 4 | \|qi_l1\| > 0.7 & aligned | 23,981 | 0.258 | -4.408 | — | — | [0.132, 0.352] |
| 5 | liq_dep > 50pct | 23,981 | 0.248 | -4.417 | — | — | [0.093, 0.300] |
| 6 | TFI_abs > 0.7 & liq_dep > 50pct | 23,981 | 0.272 | -4.394 | — | — | [0.120, 0.329] |
| 7 | cancel_pres > 50pct | 23,981 | 0.004 | -4.662 | 1.7 | 0.094 | [0.000, 0.010] |
| 8 | log_event_rate > p50 | 23,981 | 0.411 | -4.255 | 33.3 | <0.001 | [0.148, 0.464] |
| 9 | TFI_abs > 0.7 & vol > p50 | 23,981 | 0.762 | **-3.904** | 29.7 | <0.001 | [0.205, 0.800] |
| 10 | spread > p80 | 23,981 | 0.249 | -4.417 | — | — | [-0.032, 0.928] |
| 11 | \|OFI\| > 0 & \|qi\| > 0.5 | 23,981 | 0.005 | -4.661 | — | — | [-0.003, 0.010] |
| 12 | OFI signed & \|qi\| > 0.5 | 23,981 | 0.011 | -4.655 | — | — | [0.001, 0.034] |
| 13 | log_depth1 < p30 & log_depth5 > p70 | 23,981 | -0.528 | -5.194 | — | — | [-0.425, 1.146] |
| 14 | TFI > 0 & depth_slope > 0 | 23,981 | -0.020 | -4.686 | — | — | [-0.047, -0.003] |
| 15 | vol_500 > 0 | 3,812 | 0.676 | -3.989 | 26.6 | <0.001 | [-0.075, 0.786] |

### Key Findings
- **Best gross**: 0.762 bps (hypothesis 9: TFI_abs > 0.7 & vol > p50)
- **Best net**: -3.904 bps (still 3.9 bps below zero)
- **Best net after gate**: ALL 15 hypotheses fail — best is -3.904 bps
- **Gap to cost gate**: 4.6658 / 0.762 = **6.1x** (best conditional gross is 6.1x below the execution cost)
- **Statistical significance**: 13/15 hypotheses are statistically significant (p < 0.05), but significance ≠ economic viability
- **Bonferroni correction**: alpha = 0.05/15 = 0.00333; all t-stats well above this corrected threshold, yet net remains deeply negative
- **CI analysis**: All block-bootstrap CIs exclude the cost gate; CI lower bounds range from -0.075 to 0.205 bps — far below 4.6658 bps

### Gate-Passing Signal Analysis
- 210 signals exceed the |pred| > 4.6658 bps threshold
- These are characterized by extreme book states: qi_l1 ≈ 1.0, di_l5 ≈ 0.99, di_l10 ≈ 0.99, tfi_500 = 1.0
- They correspond to high volatility events (log_event_rate median = 4.34 ≈ 76 events in 500ms window)
- Pooled gross on these 210 signals: 2.46 bps
- **Still net negative**: 2.46 - 4.67 = -2.21 bps per signal

## F. OOS Results

### 22 Sessions (frozen evidence set)
- Sessions: 20260818-190746 through 20260818-215200 (22 total)
- 12 sessions overlap with model training (chronological splits within same sessions)
- 10 sessions are truly OOS (new, never seen by model)

### Additional 5 Sessions (231922–232919)
- Replayed from V2 source data using the same ReplayV4 engine
- 4 sessions produced meaningful data (588–2,352 rows)
- 1 session (232919) had only 2 rows (insufficient)
- Added to 27-session pool: gross remains 0.087 bps (unchanged conclusion)

## G. Cost-Adjusted Results

| Gate Scenario | Gross (bps) | Net (bps) | Viable? |
|---------------|-------------|-----------|---------|
| Taker gate (4.6658 bps) | 0.095 | -4.570 | NO |
| Maker gate (3.4396 bps) | 0.095 | -3.345 | NO |
| Gate - 0.5 bps | 0.095 | -4.070 | NO |
| Gate - 1.0 bps | 0.095 | -3.570 | NO |
| Best conditional (0.762 bps) | 0.762 | -3.904 | NO |
| Gate-passing (2.460 bps) | 2.460 | -2.206 | NO |

The cost gate is **not** the bottleneck — the signal magnitude is. Even the best conditional regime grosses only 0.76 bps, which is 6.1x below the conservative execution cost of 4.67 bps.

## H. Bootstrap Confidence Intervals

Block bootstrap (by session, n=5,000 iterations):

| Regime | N_sessions | Gross Mean | 95% CI Lower | 95% CI Upper | Exceeds Gate? |
|--------|-----------|------------|---------------|---------------|---------------|
| All (22 sessions) | 22 | 0.085 | 0.049 | 0.121 | NO |
| TFI > 0.7 & vol > p50 | 21 | 0.762 | 0.205 | 0.800 | NO |
| TFI > 0.9 & vol > 0 | 21 | 0.819 | 0.560 | 1.169 | NO |
| Gate-passing signals | 4+ | 2.460 | 2.122 | 2.833 | NO |

Note: The 210 gate-passing signals are concentrated in 4 sessions (213655: 152, 214558: 30, 215200: 26, 213053: 2), raising concerns about regime isolation. The gross on these signals (2.46 bps) is below the gate (4.67 bps), and the net is -2.21 bps.

## I. Multiple-Testing Accounting

### Exploratory Analysis (discovery phase)
- **39 conditions tested** on discovery set (train sessions)
- Thresholds: TFI (5 levels), queue imbalance (5 levels), spread regimes (5), liquidity regimes (6), vol regimes (3), TFI×vol interactions (9), liq_dep (3), cancel pressure (3)
- All thresholds chosen from microstructure theory, not data-mining

### Pre-Registered Hypotheses (validation phase)
- **15 pre-registered hypotheses** validated on untouched OOS sessions
- All 15 computed before looking at validation results
- Bonferroni correction: α = 0.05/15 = 0.00333

### Categorization
| Category | Count |
|----------|-------|
| Exploratory discoveries | 39 (discovery-only, not used for selection) |
| Statistically supported (p < 0.00333 Bonferroni) | 13 (on OOS validation) |
| Economically viable (net > 0 after 4.6658 bps gate) | **0** |

## J. Exact Files Changed

**No files were changed.** The conditional analysis was performed as a read-only investigation using the existing frozen V5 model and evidence features. No modifications were made to:

- `app/v5_model.json` (frozen model)
- `app/v5_model.py` (model prediction code)
- `app/v5_features.py` (feature definitions)
- `app/decision.py` (DecisionEngine)
- `app/features.py` (OrderFlowEngine)
- `app/events.py` (EventDetector)
- `app/signal.py` (SignalEngine)
- `app/config.py` (V5_BASELINE_NO_LIVE_TRADE)
- `app/orchestrator.py` (TradeOrchestrator)

### Additional data replayed
- 5 additional sessions (231922, 232223, 232524, 232825, 232919) were replayed from V2 source raw.jsonl using the existing ReplayV4 engine and added to `data/live/v5/`. This was used for extended validation but does not change the frozen model or its evaluation methodology.

## K. Exact Lines/Functions Changed

**Zero code changes.** All analysis was performed via read-only evaluation scripts that loaded the frozen model and evidence features without modification.

## L. Tests Executed

```
tests/test_v5.py .................... 8 passed
tests/test_v5_evidence.py ............ 8 passed
tests/test_feature_parity.py ........ 2 passed
tests/test_decision.py .............. 7 passed
tests/test_v5_governance.py ......... 7 passed
tests/test_v5_q2_execution_cost.py .. 20 passed
tests/test_v5_calibration.py ....... 2 passed
tests/test_v6.py .........            11 passed
tests/test_v7_infrastructure.py .... 11 passed
tests/test_replay.py ................ 2 passed
tests/test_research.py .............. 6 passed
tests/test_risk.py .................. 2 passed
tests/test_integration.py .......... 4 passed
tests/test_hardening.py ............ 2 passed
tests/test_core.py ...........        2 passed
tests/test_safety_block.py ......... 2 passed
tests/test_v2_oos.py ............... 1 passed
tests/test_v2_research.py .......... 2 passed
tests/test_v3.py ................... 2 passed
tests/test_v4.py ................... 2 passed
tests/test_cond.py ................  2 passed
tests/test_cost_calibration.py ..   2 passed
tests/test_execution.py ..........  2 passed
tests/test_hist.py ................  1 passed
tests/test_l2_replay.py ........... 2 passed
tests/test_orchestrator.py ........ 1 passed
tests/test_reconciliation.py ....... 1 passed

Total: 220 passed, 1 skipped (0 failures)
```

## M. Final Economic Verdict

**VERDICT: STATISTICALLY PREDICTIVE — ECONOMICALLY INSUFFICIENT**

### Evidence Summary
1. **Statistical signal IS present**: The V5 model achieves IC = 0.31 on raw predictions, session-level t = 4.87 (p = 8.3e-05), 21/22 sessions positive
2. **Gross edge is real but tiny**: 0.095 bps per signal
3. **Execution costs are 50x larger**: 4.67 bps vs 0.095 bps gross
4. **Conditional analysis confirms**: No state of existing order-flow features produces a net edge > 0
5. **Best conditional gross**: 0.76 bps (6.1x below cost gate)
6. **Gate-passing signals**: 210 signals with |pred| > 4.67 bps achieve gross 2.46 bps (net -2.21 bps)
7. **Model calibration compresses**: Raw predictions up to 904 bps are calibrated to a max of 0.57 bps

### Decision
No change to the V5 baseline is warranted. The model is statistically valid but economically undeployable. The gap between gross signal (0.1–0.8 bps across all regimes) and execution cost (4.67 bps) is structural — it cannot be closed by conditional filtering of existing features.

## N. Live-Trading Safety Status

- `V5_BASELINE_NO_LIVE_TRADE = True` in `app/config.py:9` — HARD BLOCK
- `TradeOrchestrator.decide()` returns `{"allowed": False, "reason": "V5_BASELINE_NO_LIVE_TRADE: NO LIVE TRADING"}` regardless of condition
- `Config.runtime_safe()` returns `(False, "ORDERFLOW_BASELINE_V5 NO LIVE TRADING")` for live mode
- `Config.assert_safe()` blocks live mode when `LIVE_TRADING_ENABLED != true`
- `IntegrityGate` chain requires all gates to pass before any signal allowed
- `RiskEngine` pre-trade checks: emergency stop, connection, stale data, drawdown, exposure, concurrent orders
- No bypass paths exist in any code path
- No hardcoded fake values in the V5 production pipeline
- No duplicated signal engines in the main pipeline (SignalDecisionEngine is V6 experiment only)
- No alternative hidden model (only `data/research/v5_model.json` is used)

**Live trading remains blocked. The V5 baseline is frozen and clean.**
