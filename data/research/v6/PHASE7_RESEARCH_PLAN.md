# Phase 7 Research Plan: Signal Formulation, Horizon, and Instrument Robustness

**Status**: RESEARCH PLAN ONLY — No implementation until approved.
**Date**: 2026-08-20
**Protocol**: Pre-registered. No post-hoc selection. No OOS fitting.

---

## 1. Scientific Question

The V6 forensic validation established:

- V6 contains statistically significant incremental information over V5 (p < 0.0001).
- Incremental gross expectancy is only ~0.0078 bps.
- Realistic execution cost is ~4.66 bps (taker) / ~3.44 bps (maker).
- Net expectancy after cost: negative. No deployable economic edge.

**The failure is not lack of predictive information. The failure is that the price response magnitude is too small relative to execution costs.**

Phase 7 asks:

> Can the existing validated order-flow information be expressed at a different pre-registered trading horizon, signal formulation, or instrument where the price response is economically large enough to survive realistic execution costs?

---

## 2. Governing Constraints

| Constraint | Enforcement |
|---|---|
| Pre-register horizon/formulation/instrument set BEFORE looking at results | Written plan + timestamp |
| No horizon selection after seeing OOS results | Locked experiment registry |
| Training/validation/OOS separation remains intact | Identical split masks as V5/V6 |
| No OOS fitting | Models frozen before OOS evaluation |
| No threshold fishing | All thresholds pre-specified |
| No arbitrary parameter optimization | Fixed ridge alpha = 1.0, no grid search |
| No synthetic order-book data | Authentic Binance USDⓈ-M data only |
| No live trading | `V5_BASELINE_NO_LIVE_TRADE = True` remains enforced |
| Primary acceptance criterion | EXPECTED NET EDGE AFTER REALISTIC CONTEMPORANEOUS EXECUTION COST > 0 on untouched OOS |

---

## 3. Pre-Registered Experimental Matrix

### 3.1 Horizons (Pre-Registered, Ordered)

| ID | Horizon (ms) | Rationale |
|---|---|---|
| H1 | 250 | Current V5/V6 baseline |
| H2 | 500 | Current V5/V6 primary |
| H3 | 1,000 | Current V5/V6 extended |
| H4 | 2,000 | Potential persistence regime |
| H5 | 5,000 | Potential mean-reversion/transition regime |
| H6 | 10,000 | Longer-horizon liquidity migration |

**Governance**: All six horizons are evaluated. The best-performing horizon is reported but NOT automatically selected for deployment.

### 3.2 Signal Formulations (Pre-Registered)

| ID | Formulation | Description |
|---|---|---|
| FA | Instantaneous OFI | Raw order-flow imbalance at time t → prediction at t+H (current V5/V6) |
| FB | Persistence-conditioned OFI | OFI(t) × persistence score (fraction of last N events with same sign) |
| FC | Liquidity-transition OFI | OFI(t) only when liquidity regime changes (tight→thin, normal→high_impact, etc.) |

### 3.3 Aggregation Modes (Pre-Registered)

| ID | Mode | Description |
|---|---|---|
| CT | Clock-time | Fixed H ms holding period (current approach) |
| ET | Event-time | H events forward, normalized by inter-event time |

### 3.4 Instruments (Pre-Registered)

| ID | Symbol | Rationale |
|---|---|---|
| I1 | BTCUSDT | Primary instrument (existing data) |
| I2 | ETHUSDT | Secondary, sufficiently liquid |
| I3 | BNBUSDT | Tertiary, sufficient liquidity |

**Note**: Each instrument requires its own contemporaneous execution cost measurement (Q2 protocol per instrument).

### 3.5 Complete Experiment Registry

The full experiment matrix contains:

```
6 horizons × 3 formulations × 2 aggregation modes × 3 instruments = 108 experiments
```

Each experiment is assigned a unique `experiment_id` following the pattern:
`H{horizon}_F{formulation}_A{aggregation}_I{instrument}`

Example: `H2_FB_CT_I1` = Horizon 500ms, Persistence-conditioned OFI, Clock-time, BTCUSDT.

---

## 4. Feature Set (Frozen from V6)

The following feature groups from V6 are used. No new features are added.

| Group | Features | Count |
|---|---|---|
| A. L1 OFI | ofi_l1, ofi_norm_l1 | 2 |
| B. Multi-level OFI | ofi_slope, ofi_persistence | 2 |
| D. Signed trade flow | tfi_500, signed_vol_500, signed_vol_momentum, vpin_500, trade_size_kyle | 5 |
| E. CVD | cvd_slope, cvd_price_divergence, cvd_acceleration | 3 |
| F. Trade intensity | trade_rate, log_event_rate | 2 |
| G. Spread | spread_bps, mpd_bps, effective_spread | 3 |
| H. Multi-level depth imbalance | qi_l1, di_l5, di_l10, di_l1_3, di_l4_7, di_l8_10, imbalance_slope | 7 |
| I. Book depletion/replenishment | liq_depletion, depth_recovery_rate, log_depth1, log_depth5 | 4 |
| J. Absorption | absorption_proxy, impact_per_volume | 2 |
| K. Flow toxicity | vpin_500, trade_size_kyle | 2 (overlap with D) |
| L. Liquidity/regime state | liq_depletion (one-hot encoded) | 1 |
| price_response | price_response_to_ofi, microprice_momentum | 2 |
| execution_cost | contemporaneous_cost_gate, cost_adjusted_signal | 2 |

**Total**: 38 features (same as V6, frozen).

---

## 5. Model Architecture (Frozen)

| Component | Specification |
|---|---|
| Baseline | V5 frozen model (17 features, ridge alpha=1.0) |
| Extension | V6 frozen model (38 features, ridge alpha=1.0) |
| Alternative | Interpretable microstructure model (Model 2): OFI + MLOFI + QI + microprice + spread + depth + trade imbalance + volatility + liquidity regime |
| ML candidates | Logistic regression, regularized linear, gradient boosting, CatBoost, small neural network — only if they demonstrate incremental OOS information after costs |

**Governance**: Models are trained on the training split ONLY, frozen before validation/OOS evaluation. No refitting on OOS data.

---

## 6. Evaluation Protocol

### 6.1 Data Splits (Identical to V5/V6)

| Split | Fraction | Purpose |
|---|---|---|
| Train | 70% | Model fitting |
| Validation | 15% | Hyperparameter tuning (if any), early stopping |
| OOS | 15% | Final evaluation ONLY |

**Governance**: OOS data is never used for training, feature selection, or threshold selection.

### 6.2 Label Construction

For each horizon H ∈ {250, 500, 1000, 2000, 5000, 10000} ms:

```
label_H = (mid_price(t+H) - mid_price(t)) / mid_price(t) * 10000  [in bps]
```

This is the executable return, already accounting for spread.

### 6.3 Cost Model

For each instrument, use the **contemporaneous** execution cost measured by the Q2 protocol:

| Cost Component | Source |
|---|---|
| Spread | p50/p90/p95/p99 from Q2 measurement |
| Slippage | Measured from Q2 sample |
| Fees | Binance USDⓈ-M taker/maker schedule |
| Impact | Almgren-Chriss framework |
| Latency | Measured round-trip |
| Adverse selection | Estimated from post-trade price movement |
| Safety margin | Pre-specified buffer |

**Governance**: Historical cost is NEVER used as a substitute for contemporaneous cost.

### 6.4 Inference

| Method | Specification |
|---|---|
| Standard errors | HAC/Newey-West |
| Max lag | min(5 × median_gap_ms / 1000, N-1) |
| Confidence intervals | 95% HAC-robust |
| Multiple testing | Bonferroni correction across all 108 experiments |

### 6.5 Metrics Reported

| Metric | Calculation |
|---|---|
| Gross expectancy (bps) | mean(sign(pred) × label_H) |
| Net expectancy (bps) | mean(sign(pred) × label_H - cost) for executed trades only |
| Statistical significance | HAC p-value for gross and net |
| Turnover | Fraction of OOS rows with |pred| > gate |
| Max drawdown | Maximum drawdown on non-overlapping executed returns |
| Sharpe | Annualized Sharpe on non-overlapping trail |
| Profit factor | Sum(positive net) / |Sum(negative net)| |
| Long/short breakdown | Net expectancy for LONG and SHORT separately |
| Regime breakdown | Net expectancy per regime (normal, high_impact, wide_spread, thin_book) |
| Win rate | Fraction of executed trades with net > 0 |

---

## 7. Specialized Analyses

### 7.1 Continuation vs. Reversal

For each experiment, decompose trades into:
- **Continuation**: OFI > 0 AND previous return > 0 (or vice versa)
- **Reversal**: OFI > 0 AND previous return < 0 (or vice versa)
- **Neutral**: no prior directional bias

Report net expectancy separately for each category.

### 7.2 Liquidity Transition Concentration

Test whether predictive power is concentrated around:
- Spread widening events (tight → wide)
- Depth depletion events (log_depth1 drops > 50% in 500ms)
- Regime changes (normal → high_impact)

Post-transition windows: [0, 500ms], [500ms, 2000ms], [2000ms, 5000ms].

### 7.3 Instrument Robustness

Each instrument requires:
1. Independent Q2 cost measurement
2. Independent OOS evaluation
3. Report whether positive net expectancy is specific to BTCUSDT or generalizes

### 7.4 Probability Calibration

If the model outputs confidence scores:
- Calibrate on validation set (Platt scaling or isotonic regression)
- Evaluate on OOS: Brier score, calibration curve, reliability, log loss, ECE
- Confidence must be statistically meaningful

### 7.5 Multiple Testing Correction

With 108 experiments, the Bonferroni-corrected significance threshold is:
```
alpha_corrected = 0.05 / 108 = 0.000463
```

An experiment is only considered statistically significant if its p-value < 0.000463.

---

## 8. Acceptance Criteria (All Must Pass)

| Criterion | Threshold |
|---|---|
| Net expectancy after contemporaneous cost | > 0 bps |
| Gross expectancy | > 0 bps |
| Gross statistical significance | HAC p < 0.000463 (Bonferroni) |
| Net statistical significance | HAC p < 0.000463 (Bonferroni) |
| Long/short symmetry | Both directions profitable or both non-significant |
| Regime robustness | Profitable in at least one non-high-impact regime |
| Turnover | ≤ 50% of OOS rows |
| Max drawdown | < 10 bps |
| Brier score (if calibrated) | < 0.25 |
| Instrument robustness | Positive net on at least one non-BTC instrument |

---

## 9. Decision Logic

| Outcome | Action |
|---|---|
| Any single experiment passes all criteria | Proceed to independent replication on new untouched data |
| No experiment passes | STOP. Report NO DEPLOYABLE ECONOMIC EDGE. |
| BTCUSDT passes but others fail | Flag as instrument-specific. Require independent replication on BTCUSDT with new data. |
| Multiple experiments pass | Select the most robust (highest net expectancy, lowest drawdown, survives multiple testing) for independent replication. |

---

## 10. Deliverables

| # | Document | Description |
|---|---|---|
| 1 | V5 frozen baseline report | Current V5 performance, frozen |
| 2 | V6 feature audit | Feature-by-feature definitions, rationales, incremental predictive value |
| 3 | Feature-by-feature predictive report | Correlation, t-stat, p-value for each feature |
| 4 | Incremental-information report | V6 vs V5, residual analysis, R² comparison |
| 5 | Execution-cost report | Q2 measurements per instrument, contemporary vs historical |
| 6 | OOS report | Full OOS results for all 108 experiments |
| 7 | Multiple-testing report | Bonferroni correction, family-wise error rate |
| 8 | Probability-calibration report | Brier score, calibration curves, reliability |
| 9 | Regime report | Performance breakdown by liquidity regime |
| 10 | Long/short symmetry report | Performance breakdown by direction |
| 11 | Independent-replication protocol | Procedure for validating any passing experiment |
| 12 | Final signal decision specification | Decision tree, gates, thresholds |
| 13 | Deployment gate report | Final verdict: NO_EDGE / CONDITIONAL_EDGE / DEPLOYABLE_EDGE |

---

## 11. What This Plan Does NOT Do

- Does NOT add more features to V6
- Does NOT optimize thresholds
- Does NOT tune hyperparameters
- Does NOT refit models on OOS data
- Does NOT enable live trading
- Does NOT select the best horizon after seeing results and call it "deployment"

---

## 12. Current Scientific Conclusion

The V5/V6 forensic validation established:

```
V5: ❌ no economic edge
V6: ❌ statistically significant incremental information, but economically insufficient
Q2: ✅ contemporaneous cost validated
Live trading: 🔴 BLOCKED
```

The next research must target the **magnitude and persistence of the price response itself**, not feature accumulation.

---

## 13. Approval Required

This research plan requires explicit approval before any implementation begins.

Approval will confirm:
1. The experimental matrix (6 horizons × 3 formulations × 2 aggregations × 3 instruments)
2. The acceptance criteria
3. The multiple-testing correction
4. The decision logic
5. The deliverables

No implementation will proceed without written approval.
