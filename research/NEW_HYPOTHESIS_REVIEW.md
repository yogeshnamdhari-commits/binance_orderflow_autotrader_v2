# New Hypothesis Research Review

**Date**: 2026-08-23  
**Status**: PRE-REGISTERED HYPOTHESIS  
**ID**: EXP-005  

---

## 1. Problem Analysis

### What V5/V6/V7 Established
- Gross signal at 500ms: +0.02 to +0.05 bps (statistically real but tiny)
- Net signal: -1.93 to -1.98 bps (after 2.0 bps maker fee)
- Cost-to-signal ratio: ~44:1
- With proper purging: signal disappears entirely

### What the Data Actually Shows

**Feature correlation analysis reveals two separate prediction problems:**

| Problem | Best Features | Correlation |
|---------|--------------|-------------|
| **Direction** (sign of return) | signed_vol_imbalance, tfi_500, di_l5, mpd_bps | +0.31 to +0.37 |
| **Magnitude** (|return|) | vpin, liq_depletion, vol_500 | +0.20 to +0.37 |

**Key insight**: The features that predict *which way* price moves are **different** from the features that predict *how far* it moves.

**Volatility regime matters:**
- Low vol: E[|r|] = 0.27 bps
- Med vol: E[|r|] = 0.50 bps  
- High vol: E[|r|] = 0.66 bps

**Tradability**: P(|r| > 2.0 bps) at 500ms = 0.72%. Only ~1 in 140 events exceeds the cost threshold.

### Why V5/V6/V7 Failed
They predicted signed return E[r|X] using a single model. But:
1. The directional signal is weak (corr ~0.3 at best)
2. The magnitude signal is separate and also weak
3. Even when direction is correct, the move is usually too small (< 0.4 bps median) to overcome 2.0 bps cost

---

## 2. New Hypothesis: Direction-Magnitude Decomposition with Selective Trading

### Core Hypothesis

> A two-stage model that separately predicts:
> 1. **Direction** using order-flow features (trade imbalance, queue imbalance)
> 2. **Magnitude** using toxicity/liquidity features (VPIN, depletion, volatility)
>
> ...can identify a **subset of events** where the expected move exceeds execution costs, producing positive net expectancy on that subset.

### Economic Mechanism

**Stage 1: Direction Prediction**
- Trade flow imbalance and queue imbalance reflect short-horizon pressure
- When aggressive buyers outnumber sellers, price is more likely to go up
- Features: `signed_vol_imbalance`, `tfi_500`, `qi_l1`, `di_l5`

**Stage 2: Magnitude Prediction**
- VPIN measures flow toxicity (informed trading)
- Liquidity depletion measures depth consumption
- When toxicity is high AND liquidity is depleted, moves are larger
- Features: `vpin`, `liq_depletion`, `vol_500`, `signed_vol_imbalance`

**Stage 3: Selective Trading Gate**
- Only trade when: P(correct direction) × E[move | direction] > cost
- This is a **joint** condition: need both direction confidence AND sufficient magnitude
- Most events will be NO_TRADE (this is correct and expected)

### Research Basis

**A. Order-Flow Direction Prediction**
- Cont, Kukanov & Stoikov (2014): OFI predicts short-horizon direction
- Gould & Bonart (2016): Queue imbalance predicts one-tick-ahead direction
- **Our data confirms**: tfi_500, di_l5, signed_vol_imbalance have +0.31-0.37 corr with direction

**B. Flow Toxicity and Magnitude**
- Easley, LdP & O'Hara (2012): VPIN measures informed trading → larger moves
- **Our data confirms**: vpin has +0.37 corr with |return|

**C. Liquidity Depletion and Impact**
- Cont, Kukanov & Stoikov (2014): Impact depends on available depth
- **Our data confirms**: liq_depletion has +0.35 corr with |return|

**D. Selective Trading / Market Impact**
- Cartea, Donnelly & Jaimungal (2015): Optimal execution considers market impact
- Almgren & Chriss (2001): Trade only when expected benefit exceeds cost
- **Our application**: Gate on expected net return, not just direction

---

## 3. Pre-Registered Methodology

### 3.1 Model Architecture

```
Stage 1: Direction Model (Classification)
  Input: trade_flow_features = [tfi_500, signed_vol_imbalance, qi_l1, di_l5, mpd_bps]
  Output: P(up | X), P(down | X)
  Model: Logistic regression (interpretable)

Stage 2: Magnitude Model (Regression)
  Input: magnitude_features = [vpin, liq_depletion, vol_500, depth_slope_bps, spread_bps]
  Output: E[|r| | X]
  Model: Ridge regression on |r|

Stage 3: Decision Gate
  expected_move = P(correct_dir) × E[|r|]
  net_edge = expected_move - cost
  Trade if: net_edge > 0 AND confidence > threshold
```

### 3.2 Features

**Direction features (5)**:
- `tfi_500`: Trade flow imbalance (signed buy/sell volume)
- `signed_vol_imbalance`: Signed volume / depth5
- `qi_l1`: Queue imbalance at touch
- `di_l5`: Distance-weighted depth imbalance (5 levels)
- `mpd_bps`: Microprice deviation from mid

**Magnitude features (5)**:
- `vpin`: Volume-synchronized probability of informed trading (proxy)
- `liq_depletion`: Aggressive volume / depth5
- `vol_500`: Short-horizon realized volatility
- `depth_slope_bps`: Log-depth decay slope
- `spread_bps`: Current spread

### 3.3 Labels

- Direction: `sign(r_500)` → {+1, -1}
- Magnitude: `|r_500|` → non-negative continuous

### 3.4 Horizons

**Primary**: 500ms (same as V5/V6/V7 for comparability)
**Secondary**: 1000ms, 2000ms (to test robustness)

### 3.5 Cost Model

- Maker fee: 2.0 bps round-trip
- Safety margin: 0.5 bps
- **Total cost: 2.5 bps**

### 3.6 Decision Gate

```
Trade if ALL of:
  1. P(direction correct) > 0.55 (directional confidence)
  2. E[|r|] > 3.0 bps (magnitude sufficient to cover cost + margin)
  3. Expected net edge = P(correct) × E[|r|] - 2.5 > 0
  4. Liquidity regime = NORMAL
  5. Spread < 3 bps

Otherwise: NO_TRADE
```

### 3.7 Validation

- Chronological split: 70/15/15
- Purged validation (remove overlapping labels)
- Walk-forward: 5 windows
- Report: % traded, gross on traded, net on traded, net on all events

### 3.8 Success Criteria

**Pass (DEPLOYABLE_EDGE)** if:
1. Net expectancy on **traded subset** > 0
2. Net expectancy on **all events** > -0.5 bps (opportunity cost small)
3. At least 5% of events are traded (sufficient signal frequency)
4. Walk-forward stable (not driven by one window)

**Fail (HYPOTHESIS_REJECTED)** if:
1. No subset produces positive net expectancy
2. Direction model does not beat 50% accuracy
3. Magnitude model does not predict |r| better than baseline

---

## 4. What Makes This Different from V5/V6/V7

| Aspect | V5/V6/V7 | New Hypothesis |
|--------|-----------|----------------|
| Target | E[r \| X] (signed) | P(dir) × E[|r|] (decomposed) |
| Model | Single model | Two-stage (direction + magnitude) |
| Gate | Sign(pred) > 0 | Joint confidence × magnitude > cost |
| Trade frequency | ~100% | ~5-20% (selective) |
| Economic logic | "Predict direction" | "Predict when move > cost" |

---

## 5. Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Overfitting with two models | Pre-registered features, purged validation |
| Too few trades | Report trade frequency; require >5% |
| Magnitude prediction weak | Use simple ridge; regularize heavily |
| Look-ahead in VPIN | VPIN computed causally (trailing window only) |
| Regime dependence | Report regime-conditional results |

---

## 6. Pre-Registration Checklist

- [x] Hypothesis defined before seeing results
- [x] Features pre-selected (5 direction + 5 magnitude)
- [x] Model classes pre-selected (logistic + ridge)
- [x] Cost model pre-defined (2.5 bps)
- [x] Decision gate pre-defined (joint condition)
- [x] Success criteria pre-defined
- [x] Validation methodology pre-defined (chrono + purged + walk-forward)

**This hypothesis is pre-registered. No parameters will be tuned against OOS data.**
