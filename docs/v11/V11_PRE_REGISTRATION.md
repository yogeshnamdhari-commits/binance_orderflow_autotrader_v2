# V11 Pre-Registration Protocol

## Status
Research-only. This document does not authorize live trading.

## Objective
Determine whether a genuinely positive order-flow edge exists on BTCUSDT with realistic execution economics.

## Background
V10 failed due to fundamental economic assumptions misaligned with BTCUSDT market reality:
- `spread_capture_bps=2.0` assumed, actual spread=0.013 bps (153x lower)
- `fee_rebate_bps=0.5` assumed, actual maker rebate=-0.02 bps (25x lower)
- Net EV with realistic assumptions: -0.406 bps/order (negative)

## V11 Design Principles
1. **Separate signal from execution**: Measure predictive signal independently from execution costs
2. **Realistic economics**: Use actual Binance fees, spreads, and execution assumptions
3. **No assumed spread capture**: Do not assume spread capture that cannot be demonstrated
4. **Parsimonious model**: Minimal features and parameters with documented rationale
5. **Pre-registered protocol**: All decisions made before seeing forward data

## Strategy Design

### A. Signal Edge
**Question**: Does order flow predict short-term price movement?

**Features** (parsimonious, documented rationale):
1. **Order flow imbalance** (OFI): Net aggressive orders in recent window
   - Rationale: Aggressive orders absorb liquidity and move price
2. **Depth imbalance**: Bid depth vs ask depth at top of book
   - Rationale: Imbalance indicates buying/selling pressure
3. **Trade direction**: Ratio of buyer-initiated trades
   - Rationale: Buying pressure typically lifts price

**Model**: Simple logistic regression (transparent, interpretable)
- Target: Price movement > spread in next 1 second
- Features: OFI, depth imbalance, trade direction
- No hidden layers, no ensembles

### B. Execution Model
**Realistic Binance BTCUSDT perpetual assumptions**:
- Maker fee: -0.02% (-0.02 bps) rebate
- Taker fee: 0.04% (0.04 bps)
- Typical spread: 0.013 bps (from observed data)
- Slippage: Depends on queue position and market conditions
- Adverse selection: Measured from data

**Execution modes tested**:
1. **Passive limit order**: Post at bid/ask, wait for fill
   - Spread capture: 0 bps (doesn't cross spread)
   - Fee: -0.02 bps (maker rebate)
   - Fill probability: Queue-dependent
2. **Aggressive market order**: Cross spread to execute immediately
   - Spread capture: Actual spread (0.013 bps)
   - Fee: 0.04 bps (taker fee)
   - Fill probability: ~100% (if size allows)
3. **Mid-price order**: Post at mid, wait for fill
   - Spread capture: Half spread (0.0065 bps)
   - Fee: -0.02 bps if filled as maker, 0.04 bps if becomes taker
   - Fill probability: Lower than passive

### C. Fill Probability
**Model**: Queue-position-dependent fill rates
- Bins: [0, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, inf] (queue ahead / displayed size)
- Calibrated on training data only
- Conservative estimates: Use lower bound of confidence interval

### D. Economic Model
**Net EV per order** = (Fill Probability × (Revenue - Costs)) - Cancellation Cost

Where:
- Revenue = Signal-driven price capture (NOT assumed spread capture)
- Costs = Fees + Slippage + Adverse Selection + Inventory + Exit
- Signal edge = Predicted price movement from order flow features

**Key difference from V10**: Revenue comes from PREDICTED SIGNAL, not assumed spread capture.

## Validation Protocol

### Phase 1: Calibration
- **Data**: New Binance BTCUSDT capture sessions (genuinely new, not V10 data)
- **Sessions**: Minimum 10 sessions, 60 seconds each
- **Features**: Order flow imbalance, depth imbalance, trade direction
- **Target**: Price movement > 0.5 bps in next 1 second
- **Model**: Logistic regression with L2 regularization
- **Temporal cutoff**: Hard cutoff between calibration and forward data

### Phase 2: Frozen Artifact
- Freeze model coefficients, feature scaler, and execution parameters
- Record provenance: session IDs, timestamps, observation counts
- Compute integrity hash
- NO forward data in artifact

### Phase 3: Independent Forward Test
- **Data**: Completely unseen forward session (temporally after calibration)
- **Procedure**:
  1. Load frozen artifact
  2. Generate features from forward order book
  3. Predict signal edge
  4. Simulate execution under 3 modes (passive, aggressive, mid)
  5. Compute net EV with realistic costs
- **Metrics**:
  - Signal accuracy (did predicted direction match realized?)
  - Fill rate by execution mode
  - Net EV by execution mode
  - Confidence intervals (bootstrap)
  - Statistical significance (permutation test)

### Phase 4: Execution-Cost Validation
- Validate assumptions against captured order book data
- Measure actual spreads, fees, slippage
- Sensitivity analysis on execution parameters
- Report conservative bounds

### Phase 5: Robustness/Regime Validation
**Pre-defined regimes**:
1. Low spread (<0.01 bps) vs high spread (>=0.01 bps)
2. Low volatility vs high volatility (based on price variance)
3. Low activity vs high activity (based on trade count)
4. Trending vs choppy (based on price autocorrelation)

**Requirement**: Edge must survive in at least 3 of 4 regimes with n>=10 per regime.

### Phase 6: Statistical Validation
- Bootstrap 95% confidence intervals for net EV
- Permutation test for signal accuracy
- Bonferroni correction for multiple tests
- Effect size (Cohen's h for proportions)
- Serial dependence check (lag-1 autocorrelation)

### Phase 7: Production Gate
**PASS requirements** (ALL must be met):
1. Signal accuracy > 50% (statistically significant)
2. Net EV > 0 after realistic execution costs (passive mode)
3. 95% CI for net EV excludes zero
4. Edge survives in >=3 of 4 regimes
5. Effect size >= 0.2 (small effect minimum)
6. No data leakage between calibration and forward
7. Frozen artifact integrity verified
8. All tests pass

**FAIL conditions** (ANY):
1. Net EV <= 0 with realistic costs
2. 95% CI includes zero
3. Statistical significance not achieved (p > 0.05)
4. Edge fails in >=2 regimes
5. Data leakage detected

## Pre-Registered Parameters

### Feature Engineering
```python
FEATURE_WINDOW_MS = 1000  # 1 second lookback
PREDICTION_HORIZON_MS = 1000  # 1 second forward
MIN_SPREAD_BPS = 0.001  # Minimum spread to consider
```

### Model
```python
MODEL_TYPE = "logistic_regression"
REGULARIZATION = "l2"
C = 1.0  # Inverse regularization strength
CLASS_WEIGHT = "balanced"  # Handle imbalanced classes
```

### Execution
```python
EXECUTION_MODES = ["passive", "aggressive", "mid"]
MAKER_FEE_BPS = -0.02
TAKER_FEE_BPS = 0.04
CANCELLATION_COST_BPS = 0.05
INVENTORY_COST_BPS = 0.2
EXIT_COST_BPS = 0.3
```

### Validation
```python
MIN_CALIBRATION_SESSIONS = 10
MIN_FORWARD_SESSIONS = 1
MIN_OBSERVATIONS_PER_SESSION = 50
BOOTSTRAP_SAMPLES = 10000
PERMUTATION_SAMPLES = 10000
SIGNIFICANCE_LEVEL = 0.05
BONFERRONI_CORRECTION = True
```

## Data Protocol

### Calibration Data
- **Source**: New Binance WebSocket captures (BTCUSDT)
- **Sessions**: 10+ sessions, 60 seconds each
- **Temporal range**: Must be BEFORE forward session
- **Format**: Same as V10 capture format
- **Storage**: `data/v11_calibration/`

### Forward Data
- **Source**: New Binance WebSocket capture (BTCUSDT)
- **Session**: 1 session, 60 seconds minimum
- **Temporal requirement**: start_ns > max(calibration end_ns) + 1 hour
- **Storage**: `data/v11_forward/<session_id>/`

### Data Separation
- Forward data NEVER enters:
  - Feature engineering decisions
  - Threshold selection
  - Parameter tuning
  - Model selection
  - Calibration
  - Execution-rule selection

## Reproducibility
- All random seeds fixed
- All versions recorded (Python, pandas, numpy, scikit-learn)
- All parameters in this document
- All artifacts hashed
- All code versioned

## Failure Criteria
V11 is considered FAILED if:
1. Signal accuracy <= 50% (no predictive power)
2. Net EV <= 0 with realistic execution costs
3. 95% CI for net EV includes zero
4. Statistical significance not achieved
5. Edge does not survive regime variation

A failed V11 is acceptable research. A false production approval is not.

## Authorization
This protocol was pre-registered on: 2026-09-05
Author: Kilo (autonomous research system)
Status: FROZEN - NO MODIFICATIONS ALLOWED AFTER THIS POINT
