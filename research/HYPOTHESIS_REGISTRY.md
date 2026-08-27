# Hypothesis Registry

## Rejected Hypotheses (Do Not Re-test)

| ID | Hypothesis | Reason for Rejection | Key Finding |
|----|-----------|---------------------|-------------|
| EXP-001 | V5 Ridge (17 OFI features, 500ms) | Cost-to-signal 25x | Gross +0.069 bps, net -1.931 bps |
| EXP-002 | V6 MLP (25 features, 500ms) | Cost-to-signal 20x | Gross +0.100 bps, net -1.900 bps |
| EXP-003 | V7 Multi-Level (46 features, 500ms) | Purged signal = 0 | Gross +0.045 → -0.003 after purge |
| EXP-004 | V7 Purged Validation | Signal vanishes | Net -2.003 bps after purging |
| EXP-005/006 | V8 Direction-Magnitude (500ms) | 88% zero returns | Gate never triggers, net -2.500 bps |
| EXP-007 | Horizon-Matched Features (1s-30s) | No predictive content | Dir accuracy 0.15-0.40 (below random) |
| EXP-008 | Volatility Regime Conditional | No regime produces profit | 82% events have zero volatility |
| EXP-009 | Order-Book Resiliency | No incremental info | R² 0.207 vs baseline 0.194 |
| EXP-010 | Multi-Horizon Ensemble | Not complementary | All ensembles worse than best single |
| EXP-011 | Long-Horizon Prediction (5-60min) | Features ~0 corr at 5min | Even perfect prediction yields +0.22 bps |
| EXP-012 | Aggressive Flow × Capacity × Fragility | Cost ceiling | Max return 3.54 bps < 4.0 bps taker cost |
| EXP-013 | Two-Stage Event + Direction (5min) | Insufficient accuracy | Required: 63.5% direction accuracy, achieved: 52.4% |
| EXP-014 | Next-Trade Direction + Book State (10s) | AUC=0.736 but |ret|=3.67 < cost | Net(taker)=-3.94 bps |
| EXP-015 | Size-Conditioned Trade-Sign (p99.9, 10s) | Strongest signal found | IC=0.18, dp=1.13 < 4.0 bps cost, net(maker)=-0.87 |
| EXP-016 | Cross-Market/Derivatives Context (funding + hourly returns) | No incremental value | Funding: -0.07 bps inc (30-day), Funding: +0.10 bps inc (730-day, negligible). Signal consistent across regimes. |
| EXP-017 | Information-Set Completeness Audit | Data audit complete | OI unavailable (D). All other dimensions acquired (A). |
| EXP-018 | Derivatives State Conditioning (funding + basis + ETH, 730-day) | No incremental value | +0.10 bps incremental (negligible). Model coef ~0. AUC unchanged. |
| EXP-017 | Information-Set Completeness Audit | Data audit complete | OI is D (unavailable). Funding/basis/cross-asset are B (partial). Liquidations require paid sub. |

### H1: Information-Per-Trade (IPT) Scaling
**Economic mechanism**: If we could batch multiple trades into a single position (one cost), the aggregated signal (0.4 bps/trade × N trades) could exceed the fixed cost (4.0 bps per batch).

**Supporting literature**: 
- Kyle (1985) — market microstructure with informed trading
- Huberman & Mishkin (1986) — batched vs. continuous trading

**Required data**: Trade timestamps and returns (available in aggTrades)

**Expected signal**: 0.4 bps/trade × N / (4.0 bps per batch) — positive for N > 10

**Cost**: Taker 4.0 bps per batch (single entry/exit) or maker 2.0 bps

**Falsification**: If IC does not increase when batching, signal is noise

### H2: Cross-Venue Lead-Lag (Cannot Test — No Data)
**Status**: DATA_INSUFFICIENT — only Binance data available

### H3: Funding Rate Microstructure (Cannot Test — No Data)
**Status**: DATA_INSUFFICIENT — funding rate history not available

### H4: Large-Tick Event Cascades
**Economic mechanism**: Large trades (>99th percentile) trigger cascading price moves that persist longer than average.

**Required data**: Trade sizes + price impact (available in aggTrades)

**Expected signal**: 99th percentile trades: dir_profit = 0.76 bps, net = -3.24 bps

**Finding**: Even the largest trades don't overcome cost — signal too weak

### H5: Momentum Regime Detection
**Economic mechanism**: During high-momentum periods, the trade-sign correlation may strengthen because price moves are larger and persistence is stronger.

**Required data**: Rolling volatility + trade data (available)

**Finding**: Signal does NOT concentrate in high-volatility regimes — correlation is ~constant at 0.05-0.15 regardless of volatility level

## Conclusion

### Research Space Exhausted — ECONOMICALLY_IMPOSSIBLE

All scientifically justified hypotheses have been tested across 15 experiments
spanning 13 research domains. The fundamental constraints are:

#### Constraint 1: Signal Strength
- **Trade-sign IC**: 0.01-0.18 at all horizons (weakest at longer horizons)
- **Book feature IC** (V4 sessions): 0.26 for direction, but sessions lack large moves
- **Trade-size amplified IC** (p99.9 trades at 10s): 0.18 (strongest signal found)

#### Constraint 2: Cost-to-Signal Ratio
- **Cost per trade**: 4.0 bps (taker) or 2.0 bps (maker)
- **Achievable directional profit**: 0.26-1.21 bps
- **Edge/cost ratio**: 0.066-0.30 (signal covers 7-30% of cost)

#### Constraint 3: Horizon Trade-off
| Horizon | E[|ret|] | IC | Perfect Net (taker) | Required Acc | Achieved Acc |
|---------|---------|-----|-------------------|-------------|-------------|
| 5s | 2.58 | 0.123 | -1.43 bps (negative) | Impossible | ~52% |
| 10s | 3.60 | 0.083 | -0.41 bps (negative) | Impossible | ~51% |
| 30s | 5.35 | 0.055 | +1.35 bps | 84.2% | ~51% |
| 60s | 8.28 | 0.045 | +4.27 bps | 74.2% | ~51% |
| 5min | 15.38 | 0.012 | +11.77 bps | 62.7% | ~50% |

At 5s-10s, even PERFECT prediction yields negative net (returns too small).
At 30s+, perfect prediction is positive, but achievable accuracy (50-52%)
is far below required (74-84%).

#### Constraint 4: Data Incompatibility
- **730-day trade data**: Has large moves (80.6% event rate at 5min) but only trade prices/sizes/directions — no book features, IC = 0.01
- **V4/V5 session data**: Has full book features (IC = 0.26 for direction) but sessions are too short (178s) and quiet (max |ret| = 7.8 bps)
- **No data source combines** book features AND large moves at the same horizon

#### Constraint 5: Structural Impossibility
- Required IC for 5min breakeven (taker): ~0.30
- Achievable IC (trade-sign): 0.01-0.18 (strongest at p99.9, 10s)
- Gap: 0.12-0.29 IC points — trade-size amplification (IC=0.18) still insufficient
- Even at p99.99: dp=1.66 bps < 4.0 bps cost, net(maker)=-0.34 bps (CI crosses 0)

### Terminal Verdict: **NO_DEPLOYABLE_EDGE_WITH_CURRENT_INFORMATION_SET**

The Binance BTCUSDT order-flow microstructure, as represented by the currently
available datasets and execution-cost model, does not contain sufficient
predictable information to overcome execution costs.

**Important distinction**: This conclusion applies to the *current information
set and execution assumptions*. It does NOT claim that no profitable strategy
exists anywhere in cryptocurrency markets.

#### Key Scientific Distinction

The research has moved from:
- "We can't find a predictive signal."
to:
- "We can detect predictive information, but its economic magnitude is smaller
  than the execution-cost barrier."

The p99.9 size-conditioned trade-sign signal (IC = 0.18) is the strongest
predictive signal discovered in the entire research program. Its walk-forward
stability (IC = 0.15-0.16 across 5 windows) confirms it is not overfit.

However, 1.20 bps gross directional profit vs 4.0146 bps taker cost yields
net = -2.88 bps, even with perfect execution.

#### Remaining Untested Dimensions (Not Part of Current Information Set)

1. **Cross-market information**: BTC vs ETH, spot vs perpetual (data not available)
2. **Funding rates**: Periodic funding signal (data not available)
3. **Open interest / liquidations**: Flow toxicity signal (data not available)
4. **Rich order-book data at scale**: V5 sessions are too short (178s) for medium-horizon validation
5. **Lower execution costs**: Maker-only strategy with book placement (sessions too quiet to validate)
6. **Dataset compatibility**: 730-day trade data lacks book features; V4/V5 sessions lack large moves

#### Next Scientifically Justified Steps

A. **Execution economics**: Determine if actual execution cost can be < 2 bps with
   realistic book-placement/maker strategy
B. **Horizon optimization**: Test whether the 10s signal has economic value at
   alternative horizons (pre-specified, not optimized on test data)
C. **Information set expansion**: Acquire cross-market, funding, or liquidation data
D. **Instrument selection**: Test whether the same signal appears on other liquid
   perpetuals with more favorable cost-to-signal ratios

This is a statistically and economically valid negative result for the current
information set.
