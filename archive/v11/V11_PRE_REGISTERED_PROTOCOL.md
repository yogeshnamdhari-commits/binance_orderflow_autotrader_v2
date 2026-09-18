# V11 PRE-REGISTERED VALIDATION PROTOCOL

**Version:** V11
**Timestamp:** 2026-09-05T09:02:22+05:30
**Status:** FROZEN — NO MODIFICATIONS ALLOWED AFTER THIS POINT
**Archive:** archive/v11/V11_PRE_REGISTERED_PROTOCOL.json

---

## 1. TARGET

Determine whether a **confidence-thresholded gradient-boosted order-flow strategy** on Binance BTCUSDT perpetual futures produces **positive net expected value** after realistic execution costs.

**Null hypothesis (H0):** Net EV per order ≤ 0 bps after taker execution costs.
**Alternative hypothesis (H1):** Net EV per order > 0 bps after taker execution costs.

**Economic mechanism:** The strategy exploits non-linear order-flow signal interactions (captured by gradient boosting) that exceed execution costs only when prediction confidence is above a dynamically calibrated breakeven threshold. Low-confidence predictions are filtered out to avoid adverse selection and fee burn.

---

## 2. HORIZON

- **Primary horizon:** 500ms (matches V5/V6 baseline, comparable microstructure)
- **Secondary horizons tested:** 5s (to test if longer horizons have larger moves)
- **Decision horizon:** 500ms (signal evaluated at 500ms forward mid-price return)

---

## 3. FEATURES

**Source:** V5/V6 order-flow feature set (parsimonious, microstructurally motivated)

| Feature | Definition | Rationale |
|---------|-----------|-----------|
| ofi_l1 | Level-1 order-flow imbalance | Cont et al. (2014) |
| ofi_norm_l1 | Depth-normalized OFI | Impact/depth ratio |
| qi_l1 | Queue imbalance (bid-ask)/(bid+ask) | Touch imbalance |
| di_l5 | Distance-weighted 5-level depth imbalance | Multi-level resilience |
| di_l10 | Distance-weighted 10-level depth imbalance | Deeper resilience |
| mpd_bps | Microprice deviation from mid (bps) | Fair-value dislocation |
| spread_bps | Bid-ask spread (bps) | Liquidity state |
| bid_cancel_bps | Bid cancel pressure (bps) | Cancellation flow |
| ask_add_bps | Ask add pressure (bps) | Addition flow |
| cancel_pressure | Total cancel/depth ratio | Toxicity proxy |
| tfi_500 | Trade-flow imbalance (500ms) | Signed volume pressure |
| liq_depletion | Liquidity consumption ratio | Sweep intensity |
| log_depth1 | Log top-of-book depth | Liquidity availability |
| log_depth5 | Log 5-level depth | Deeper liquidity |
| log_event_rate | Log trade event rate | Activity level |
| depth_slope_bps | Log-depth decay slope | Book shape |
| vol_500 | Realized volatility (500ms, bps) | Regime state |

**Feature engineering:**
- Raw features only (no forward-looking transformations)
- No technical indicators (no RSI/EMA/VWAP)
- No feature selection after seeing forward results
- All features computed causally from data observed at event time

**Total features:** 17 (V5_FEATURES exact set)

---

## 4. MODEL

**Algorithm:** Gradient boosting (scikit-learn `GradientBoostingClassifier`)
- `n_estimators`: 100
- `max_depth`: 3
- `learning_rate`: 0.1
- `min_samples_split`: 1000
- `min_samples_leaf`: 500
- `subsample`: 0.8
- `max_features`: 'sqrt'
- `random_state`: 42

**Rationale:**
- Gradient boosting can capture non-linear interactions between order-flow features
- Shallow trees (max_depth=3) prevent overfitting to microstructure noise
- Subsampling and min_samples provide regularization
- More expressive than V5 ridge regression but still parsimonious

**Target variable:**
- Binary classification: `y = 1` if 500ms forward mid-price return > 0, else `y = 0`
- Regression alternative: predict 500ms forward return magnitude in bps

**Training protocol:**
- Chronological train/validation split: 70% train, 15% validation, 15% test
- No random shuffling (preserves temporal dependence)
- No hyperparameter tuning after seeing validation results

**Calibration:**
- Platt scaling on validation set to convert model scores to probabilities
- Breakeven threshold derived from validation set execution costs

---

## 5. PARAMETERS

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| horizon_ms | 500 | Matches V5/V6 baseline |
| notional_usd | 10,000 | Standard position size |
| taker_fee_bps | 5.0 | Binance BTCUSDT taker fee (0.05%) |
| maker_fee_bps | 2.0 | Binance BTCUSDT maker fee (0.02%) |
| slippage_bps | 0.5 | Conservative estimate from market data |
| adverse_selection_bps | 0.5 | Conservative estimate |
| latency_bps | 0.1 | Network + processing latency |
| min_fill_prob | 0.50 | Minimum acceptable fill probability |
| safety_margin_bps | 0.5 | Additional safety buffer |

---

## 6. THRESHOLDS

**Breakeven threshold (dynamic):**
- Computed from validation set: `threshold = (taker_fee_bps + slippage_bps + adverse_selection_bps + safety_margin_bps) / expected_return_per_confidence_unit`
- Simplified: Only trade when `model_probability > 0.55` AND `|predicted_return| > 6.0 bps`
- 6.0 bps = taker fee (5.0) + slippage (0.5) + adverse selection (0.5) + safety margin (0.5) + minimum profit (0.0)

**Rationale:**
- 0.55 probability threshold ensures we only trade when model is mildly confident
- 6.0 bps predicted return ensures gross edge exceeds all realistic costs
- Thresholds derived from validation data, not forward data

**Liquidity filter:**
- Only trade when `spread_bps < 5.0` (avoid stressed markets)
- Only trade when `log_depth5 > 10` (ensure minimum depth)

**Toxicity filter:**
- Only trade when `toxicity_state != "HIGH_TOXICITY"`
- Avoid adverse selection regimes

---

## 7. EXECUTION ASSUMPTIONS

| Component | Assumption | Source | Conservative? |
|-----------|-----------|--------|---------------|
| Taker fee | 5.0 bps | Binance official | Yes (worst-case VIP 0) |
| Maker fee | 2.0 bps | Binance official | Yes (worst-case VIP 0) |
| Slippage | 0.5 bps | Market data estimate | Yes (conservative) |
| Adverse selection | 0.5 bps | Market data estimate | Yes (conservative) |
| Latency | 0.1 bps | Engineering estimate | Yes |
| Fill probability | Modeled, not assumed | Binance fill model | Yes |
| Spread capture | 0.0 bps (taker crosses spread) | Market reality | Yes |

**Execution model:**
- Taker market orders (cross spread, immediate execution)
- NO passive limit orders (V10 failure mode)
- NO assumed spread capture
- NO assumed maker rebates (we pay taker fees)
- Fill modeled as: `fill_price = mid + slippage + half_spread` for buys, `mid - slippage - half_spread` for sells
- Partial fills modeled with probability `min(1.0, depth / notional)`

---

## 8. TRANSACTION-COST MODEL

**Per-order cost (taker):**

```
total_cost_bps = taker_fee_bps + slippage_bps + adverse_selection_bps + latency_bps
               = 5.0 + 0.5 + 0.5 + 0.1
               = 6.1 bps
```

**Breakeven required return:** 6.1 bps gross per order

**Net EV calculation:**
```
net_ev = (fill_prob * predicted_return) - total_cost_bps
```

**Cost validation:**
- Taker fee: validated against Binance official fee schedule
- Slippage: estimated from observed order book depth and market impact models
- Adverse selection: estimated from post-trade price movement analysis
- All costs validated against actual Binance market data before forward test

---

## 9. PRIMARY METRIC

**Net expected value per order (bps)** after all execution costs

**Formula:**
```
net_ev_bps = (P(fill) × E[return | fill]) - total_cost_bps
```

**Decision rule:**
- net_ev_bps > 0: POSITIVE_EXPECTANCY
- net_ev_bps ≤ 0: NOT_ECONOMICALLY_VIABLE

**Secondary metrics:**
- Gross edge (bps)
- Fill rate
- Sharpe ratio (daily)
- Maximum drawdown
- Calibration slope (reliability)

---

## 10. MINIMUM EVIDENCE REQUIREMENTS

To declare V11 PASS, ALL of the following must be met:

1. **Sample size:** ≥ 100 independent forward observations
2. **Statistical significance:** One-sided t-test, p < 0.05
3. **Effect size:** Cohen's d ≥ 0.3 (small effect minimum)
4. **Confidence interval:** 95% CI lower bound > 0
5. **Permutation test:** p < 0.05
6. **Regime robustness:** Positive net EV in ≥ 2 of 3 predefined regimes
7. **Execution-cost validation:** All cost assumptions validated against market data
8. **No p-hacking:** No parameter changes after forward exposure

---

## 11. FAILURE CRITERIA

V11 is marked FAILED if ANY of the following occur:

1. Net EV ≤ 0 in forward test (primary metric)
2. 95% CI includes zero
3. p-value ≥ 0.05
4. Sample size < 100 forward observations
5. Any parameter/threshold modified after forward exposure
6. Execution costs found to be higher than assumed (net EV becomes negative)
7. Adverse selection > 2.0 bps (invalidates model assumptions)
8. Fill rate < 30% (execution model broken)

---

## 12. DATA PROTOCOL

**Calibration dataset:**
- Source: Binance BTCUSDT perpetual futures
- Type: 100ms L2 order book depth + trades
- Period: 2026-09-01 to 2026-09-05 (new data, not used in any prior version)
- Size: Minimum 10 sessions, ≥ 5,000 observations
- Split: 70% train, 15% validation, 15% test (chronological)

**Forward dataset:**
- Source: Binance BTCUSDT perpetual futures
- Period: 2026-09-06 to 2026-09-10 (completely unseen, after calibration)
- Size: Minimum 5 sessions, ≥ 500 observations
- Temporal gap: ≥ 24 hours between calibration end and forward start

**Chronological separation rules:**
- Calibration/training MUST complete before forward data is accessed
- Forward data MUST NOT be used for: feature engineering, threshold selection, parameter tuning, model selection, calibration, execution-rule selection
- Model artifact frozen immediately after calibration

**Data provenance:**
- All raw data hashed and stored in `archive/v11/calibration_sessions/`
- Forward data hashed and stored in `archive/v11/forward_sessions/`
- Manifest files record exact timestamps, session IDs, event counts

---

## 13. PRE-REGISTRATION COMMITMENT

This protocol is committed at timestamp `2026-09-05T09:02:22+05:30`.

**No modifications to the following are permitted after this timestamp:**
- Target definition
- Horizon
- Feature set
- Model algorithm and hyperparameters
- Threshold values
- Execution assumptions
- Transaction-cost model
- Primary metric
- Minimum evidence requirements
- Failure criteria
- Data protocol

**Permitted modifications (with documentation):**
- Bug fixes that do not change the scientific protocol
- Code refactoring that preserves exact mathematical behavior
- Addition of logging/observability

**Changes to the protocol require:**
1. Documented rationale
2. Version increment (V11.1, V11.2, etc.)
3. Separate archive entry
4. Explicit acknowledgment that prior results are not comparable

---

## 14. SCIENTIFIC RIGOR COMMITMENTS

1. **No p-hacking:** Once forward data is exposed, NO parameters, thresholds, features, or models may be changed
2. **No selection bias:** All calibration sessions are used; no cherry-picking
3. **No hindsight bias:** Forward results are evaluated exactly as pre-registered
4. **Transparent reporting:** All results reported, including failures
5. **Reproducible artifacts:** All code, data hashes, and model artifacts archived
6. **Honest failure:** If V11 fails, it is recorded as FAILED with economic diagnosis

---

## 15. ECONOMIC MECHANISM SUMMARY

V11 tests whether:

**Gradient boosting + confidence-thresholded execution > execution costs**

The gradient boosting model captures non-linear order-flow interactions. The confidence threshold filters out predictions where the model is uncertain, ensuring only high-conviction trades are executed. The economic mechanism is:

1. **Signal edge:** Gradient boosting extracts more predictive power than linear models
2. **Filtering:** Confidence threshold removes low-quality predictions
3. **Execution:** Taker orders ensure execution but pay taker costs
4. **Breakeven:** Only trade when predicted return exceeds total cost (6.1 bps)

**Prior evidence suggests this will fail** because:
- Max observed return (3.54 bps) < taker cost (4.0146 bps)
- This is a data-theoretic limitation, not a modeling limitation
- Even perfect prediction cannot overcome costs

**But V11 must be tested rigorously to confirm or refute this conclusion with new data and a new modeling approach.**

---

## 16. GATE TABLE (PRE-REGISTERED)

| Gate | Requirement | Pass Criterion |
|------|------------|----------------|
| Research/OOS | Model trained and validated on calibration data | AUC > 0.55 on validation set |
| Data provenance | Calibration and forward data properly sourced and hashed | All hashes verified |
| Frozen model | Model artifact frozen before forward exposure | checksum matches |
| Independent forward test | Forward data unseen during calibration | n ≥ 500 observations |
| Execution-cost validation | All cost assumptions validated against market data | Costs within 20% of estimates |
| Regime robustness | Positive net EV in ≥ 2/3 regimes | Regime classification stable |
| Statistical robustness | One-sided t-test p < 0.05, 95% CI lower > 0 | Both criteria met |
| Evidence-chain integrity | No protocol violations documented | Zero violations |
| Paper trading | Required only if all prior gates pass | N/A until then |
| Production authorization | Required only if paper trading succeeds | N/A until then |

---

**END OF PRE-REGISTERED PROTOCOL**

This document is immutable. Any changes require a new version (V11.1, V11.2, etc.) and documented rationale.
