# V7 Research Hypothesis: Multi-Dimensional Order-Flow Microstructure Model

**Date**: 2026-08-22  
**Status**: HYPOTHESIS (not yet tested)  
**Author**: Autonomous Research Agent  

---

## 1. Problem Statement

V5 (Ridge, 17 OFI features) and V6 (MLP, 25 features) both produced statistically
positive gross expectancy (+0.07–0.10 bps) but negative net expectancy after the
2.0 bps maker fee. The signal-to-cost ratio is approximately 1:20 — the hypothesis
is economically falsified.

The question for V7 is NOT "can we predict direction slightly better?" but rather:
**"Are there microstructure features that predict larger, more executable moves?"**

---

## 2. Research Foundation

### 2.1 Order-Flow Imbalance (OFI) — Cont, Kukanov & Stoikov (2014)

**Source**: Cont, R., Kukanov, A., & Stoikov, S. (2014). "The Price Impact of Order
Book Events." *Journal of Financial Econometrics*, 12(1), 47–88.

**Key Finding**: Short-horizon price changes are strongly related to order-flow
imbalance. Price impact depends on available market depth.

**Implication for V7**: OFI is a valid signal direction, but impact is
depth-dependent. This means we must normalize by depth AND consider that the
same OFI has different price impact depending on current liquidity.

**Current V5/V6 limitation**: V5 uses ofi_norm_l1 (OFI/depth1) but does not model
the interaction between OFI and the full book state dynamically.

### 2.2 Multi-Level OFI — Xu, Gould & Howison (2017)

**Source**: Xu, H., Gould, M. D., & Howison, S. D. (2017. "Multi-Level Order-Flow
Imbalance in a Limit Order Book." *Market Microstructure and Liquidity*.

**Key Finding**: Incorporating progressively deeper order-book levels improved
out-of-sample explanatory power for mid-price changes. Information beyond the best
bid/ask contains predictive signal.

**Implication for V7**: The current V5/V6 only uses L1 OFI. We should compute
OFI at multiple depth levels (L1, L2, L3, L5, L10) and use their weighted
combination. The weights should be inversely proportional to level depth
(nearer levels matter more).

**New features this enables**:
- ofi_l2, ofi_l3, ofi_l5, ofi_l10 (per-level signed depth changes)
- mlofi_weighted (weighted sum with inverse-level decay)
- ofi_decay_slope (how OFI distributes across levels — steep = localized, flat = broad)

### 2.3 Queue Imbalance as Price Predictor — Gould & Bonart (2016)

**Source**: Gould, M. D., & Bonart, J. (2016). "Queue Imbalance as a One-Tick-Ahead
Price Predictor." *Market Microstructure and Liquidity*.

**Key Finding**: Bid/ask queue imbalance contains statistically significant
predictive information for the next mid-price movement. Logistic models using
queue imbalance outperform random classifiers.

**Implication for V7**: Queue imbalance (B-A)/(B+A) at multiple levels, combined
with queue dynamics (rate of change, acceleration) may capture short-horizon
pressure better than static imbalance.

**New features this enables**:
- qi_l1, qi_l2, qi_l5 (queue imbalance at multiple levels)
- qi_slope (rate of change of queue imbalance)
- qi_acceleration (second derivative)
- queue_asymmetry (difference between bid-side and ask-side queue changes)

### 2.4 Deep Order Flow Imbalance — Kolm, Turiel & Westray (2021)

**Source**: Kolm, P. N., Turiel, J., & Westray, N. (2021). "Deep Order Flow
Imbalance." *Mathematical Finance*.

**Key Finding**: Models using stationary order-flow-derived inputs can outperform
models trained directly on raw order-book states across multiple horizons.
The key insight: engineer economically meaningful stationary microstructure
features FIRST, then model.

**Implication for V7**: This directly supports our approach of feature engineering
over model complexity. The lesson from V5→V6 (MLP did not help) confirms this.
For V7: focus on better stationary features, not a bigger model.

**Key principle**: Stationarity > Complexity

### 2.5 Microprice Dynamics — Stoikov (2018) & Cartea, Jaimungal & Penalva (2015)

**Source**: Cartea, A., Jaimungal, S., & Penalva, J. (2015). *Algorithmic and High-
Frequency Trading*. Cambridge University Press.

**Key Finding**: The microprice (volume-weighted mid) is a better estimate of
the "fair price" than the simple mid. Dislocation between microprice and mid
predicts mean-reversion toward the microprice.

**Implication for V7**: Microprice dislocation and its dynamics (speed of
mean-reversion, persistence) may predict short-horizon moves better than
static features.

**New features this enables**:
- microprice_deviation_bps (current microprice - mid, in bps)
- microprice_velocity (rate of change of microprice deviation)
- microprice_reversion_speed (how fast dislocation corrects)

### 2.6 Trade-Flow Toxicity — Easley, Lopez de Prado & O'Hara (2012)

**Source**: Easley, D., Lopez de Prado, M. M., & O'Hara, M. (2012). "Flow Toxicity
and Liquidity in a High-Frequency World." *Review of Financial Studies*, 25(5),
1457–1493.

**Key Finding**: Order flow can be toxic (informed traders adversely selecting
market makers). The VPIN (Volume-Synchronized Probability of Informed Trading)
metric measures this toxicity. Periods of high toxicity have wider spreads,
higher volatility, and more adverse selection.

**Implication for V7**: We should condition signals on toxicity regime. High
toxicity = wider spreads = higher adverse selection cost = no trade (even if
gross signal is positive).

### 2.7 Backtest Overfitting — Bailey & Lopez de Prado (2014)

**Source**: Bailey, D. H., & Lopez de Prado, M. M. (2014). "The Deflated Sharpe
Ratio: Correcting for Selection Bias, Non-Normality, and Track Record Length."
*Journal of Portfolio Management*.

**Key Finding**: Repeated strategy/model selection can manufacture apparently
strong historical results through selection bias. The Deflated Sharpe Ratio
corrects for multiple testing.

**Implication for V7**: We will test ONE pre-registered hypothesis. We will NOT
iterate on features/horizons/thresholds until the backtest turns green. The
horizon, feature set, and model architecture are pre-registered below.

---

## 3. Pre-Registered V7 Hypothesis

### 3.1 Core Hypothesis

> A model using multi-level order-flow imbalance, multi-level queue imbalance,
> microprice dynamics, and trade-flow toxicity — conditioned on liquidity regime —
> can identify short-horizon (250ms–1000ms) price moves whose expected gross
> magnitude exceeds realistic execution costs, with statistical significance
> after multiple-testing correction.

### 3.2 Feature Families (Pre-Registered)

| Family | Features | Research Basis |
|--------|----------|----------------|
| Multi-Level OFI | ofi_l1..l10, mlofi_weighted, ofi_decay_slope | Xu, Gould & Howison (2017) |
| Queue Imbalance | qi_l1..l5, qi_slope, qi_accel, queue_asymmetry | Gould & Bonart (2016) |
| Microprice Dynamics | mp_dev, mp_vel, mp_reversion_speed | Cartea et al. (2015) |
| Trade-Flow Toxicity | vpin, kyle_lambda, signed_vol_imbalance | Easley, LdP & O'Hara (2012) |
| Liquidity/Depth | depth_slope, depth_arb, spread_percentile, liq_regime | Cont, Kukanov & Stoikov (2014) |
| Volatility | vol_500, vol_ratio (short/long), vol_of_vol | Kolm et al. (2021) |
| Cross-Level Interactions | ofi_x_qi, mlofi_x_spread, depth_x_toxicity | Domain-motivated |

### 3.3 Horizon (Pre-Registered)

**Primary**: 500 ms (same as V5/V6 for comparability)  
**Secondary**: 250 ms, 1000 ms (tested but not used for primary signal selection)

Rationale: The horizon is pre-registered and not optimized. The economic question
is whether the NEW features produce a larger gross signal at the SAME horizon,
not whether a different horizon makes V5/V6 profitable.

### 3.4 Model Architecture (Pre-Registered, Staged)

```
Model 0: Naive baseline (predict mean return)
Model 1: Logistic regression (directional: up/down/neutral)
Model 2: Ridge regression (expected return magnitude, same as V5 but new features)
Model 3: Gradient boosting (LightGBM/XGBoost) ONLY if Model 2 shows edge
```

**Gating principle**: Only proceed to Model 3 if Model 2 demonstrates positive
net expectancy in OOS validation. Do not use model complexity as a substitute
for signal quality (Kolm et al. 2021).

### 3.5 Economic Decision Engine (Pre-Registered)

```
Expected Net Edge = E[R_gross | X] - E[cost | X] - E[adverse_selection | X] - E[slippage | X]

Trade only if:
1. Expected Net Edge > 0 (pointwise)
2. Bootstrap 95% CI lower bound > 0 (statistical)
3. Toxicity regime != HIGH_TOXICITY (regime filter)
4. Liquidity regime == NORMAL (liquidity filter)
5. Spread < 3 bps (transaction cost filter)
```

### 3.6 Validation Protocol (Pre-Registered)

1. Chronological train/validation/OOS split (70/15/15)
2. Purged validation (no overlapping labels)
3. Bootstrap 95% CI on net expectancy
4. HAC-robust standard errors (Newey-West)
5. Deflated Sharpe Ratio (Bailey & Lopez de Prado)
6. Ablation study (feature family removal)
7. Regime-conditional performance

---

## 4. What Makes V7 Different from V5/V6

| Aspect | V5/V6 | V7 |
|--------|--------|-----|
| OFI | L1 only | L1–L10 with decay structure |
| Queue Imbalance | Static L1 only | Multi-level + dynamics |
| Microprice | Static deviation | Deviation + velocity + reversion |
| Trade Flow | Simple TFI | Toxicity-conditioned |
| Liquidity | Static regime | Dynamic regime switching |
| Model | Ridge or MLP | Staged: Logistic → Ridge → GBM |
| Edge Estimation | Pointwise | CI + toxicity + liquidity gates |

---

## 5. Acceptance Criteria (Pre-Registered)

V7 passes if ALL of:
1. OOS net expectancy > 0 (after maker fee + safety margin)
2. Bootstrap 95% CI lower bound > 0
3. At least 5% of OOS observations exceed the execution gate
4. Performance is stable across both sessions (not driven by one)
5. Performance is stable in NORMAL liquidity regime
6. Ablation study shows incremental value from multi-level features

V7 fails if ANY of:
1. OOS net expectancy <= 0
2. Bootstrap 95% CI includes 0
3. Performance is driven by one session or one regime
4. Gross expectancy remains < 0.5 bps (still consumed by costs)

---

## 6. Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Overfitting with more features | Strict chronological splits, purged validation, pre-registration |
| Feature multicollinearity | Regularization, VIF analysis, staged model |
| Insufficient edge at any horizon | Pre-registered stop: declare NO_EDGE if criteria not met |
| Data quality (same sessions) | All models use identical data; comparison is fair |
| Look-ahead bias | All features computed strictly from past events |

---

## 7. Conclusion

V7 is a pre-registered, research-supported hypothesis that addresses the specific
failure mode of V5/V6: the gross signal was too small to overcome costs. V7 aims
to find larger, more executable moves by:

1. Using multi-level order-flow information (not just L1)
2. Modeling queue dynamics (not just static imbalance)
3. Capturing microprice mean-reversion (not just static deviation)
4. Conditioning on toxicity regime (avoid adverse selection)
5. Using staged model complexity (not jumping to black boxes)

The hypothesis must earn the right to survive validation. If it fails, we declare
NO_DEPLOYABLE_EDGE and do not iterate.
