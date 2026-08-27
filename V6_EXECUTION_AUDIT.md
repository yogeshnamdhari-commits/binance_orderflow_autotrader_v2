# V6 EXECUTION AUDIT

**Date:** 2026-08-26
**Objective:** Document execution simulation results for V6 features

---

## EXECUTION ASSUMPTIONS (FROZEN)

| Parameter | Value | Source |
|---|---|---|
| Taker fee (round-trip) | 4.0 bps | Binance |
| Maker fee (round-trip) | 2.0 bps | Binance |
| Slippage (p90, 1K notional) | 0.008 bps | Measured |
| Latency cost | 0.050 bps | Measured |
| Adverse selection | 0.500 bps | Estimated |
| Fill probability (maker) | 70% | Measured |
| Total maker cost | 2.558 bps | Sum of above |

---

## EXECUTION SIMULATION RESULTS

| Feature | Gross (bps) | Net Taker (bps) | Net Maker (bps) | Expected Net Maker (bps) | Break-Even Cost (bps) |
|---|---|---|---|---|---|
| absorption_ratio | 0.002 | -4.664 | -2.556 | -1.789 | 0.002 |
| vamp_deviation | 0.120 | -4.546 | -2.438 | -1.707 | 0.120 |
| resiliency | 0.003 | -4.663 | -2.555 | -1.788 | 0.003 |
| convexity | 0.001 | -4.665 | -2.557 | -1.790 | 0.001 |
| flow_persistence | -0.005 | -4.671 | -2.563 | -1.794 | -0.005 |
| spread_regime | 0.001 | -4.664 | -2.557 | -1.790 | 0.001 |
| flow_pressure | 0.002 | -4.664 | -2.556 | -1.789 | 0.002 |

**Expected Net Maker = Fill_Prob × Net_Maker (accounts for unfilled orders)**

---

## COST BREAKDOWN (Best Feature: vamp_deviation)

| Cost Component | bps | % of Gross |
|---|---|---|
| Gross edge | +0.120 | 100% |
| Maker fee | -2.000 | 1667% |
| Slippage | -0.008 | 7% |
| Latency | -0.050 | 42% |
| Adverse selection | -0.500 | 417% |
| **Total cost** | **-2.558** | **2132%** |
| **Net** | **-2.438** | **-2032%** |

**Execution costs are 21x larger than the gross edge.**

---

## MAXIMUM ADVERSE EXCURSION

| Feature | Max Adverse (bps) | Max Favorable (bps) | Std (bps) |
|---|---|---|---|
| absorption_ratio | -3.174 | 4.292 | 0.556 |
| vamp_deviation | -4.292 | 3.718 | 0.556 |
| resiliency | -3.827 | 3.718 | 0.556 |
| convexity | -3.190 | 4.292 | 0.556 |
| flow_persistence | -3.827 | 4.292 | 0.556 |
| spread_regime | -3.190 | 4.292 | 0.556 |
| flow_pressure | -3.174 | 4.292 | 0.556 |

**Maximum adverse excursion is 36x larger than gross edge.**

---

## FILL PROBABILITY SENSITIVITY

| Fill Probability | Expected Net Maker (vamp_deviation) |
|---|---|
| 50% | -1.219 bps |
| 60% | -1.463 bps |
| 70% | -1.707 bps |
| 80% | -1.951 bps |
| 90% | -2.194 bps |
| 100% | -2.438 bps |

**Even with 100% fill probability, net remains deeply negative.**

---

## COST SENSITIVITY

| Maker Cost | Net (vamp_deviation) |
|---|---|
| 0.0 bps | -0.120 bps |
| 0.5 bps | -0.620 bps |
| 1.0 bps | -1.120 bps |
| 1.5 bps | -1.620 bps |
| 2.0 bps | -2.120 bps |
| 2.558 bps (actual) | -2.438 bps |

**Break-even requires maker cost < 0.120 bps (impossible on Binance).**

---

## COMPARISON: V5 vs V6 EXECUTION

| Metric | V5 Baseline | V6 Best (vamp_deviation) |
|---|---|---|
| Gross | 0.174 bps | 0.120 bps |
| Net (maker) | -1.826 bps | -2.438 bps |
| Net (taker) | -4.492 bps | -4.546 bps |
| Break-even cost | 0.174 bps | 0.120 bps |

**V6 does NOT improve over V5 baseline.**

---

## CONCLUSION

Execution simulation confirms that no V6 feature can produce positive net expectancy:
1. **Execution costs dominate:** 21x larger than gross edge
2. **Fill probability doesn't help:** Even 100% fill leaves net negative
3. **Cost sensitivity:** Break-even requires impossible cost reduction
4. **Maximum adverse >> gross edge:** Risk/reward is unfavorable

The information gap cannot be closed by further feature engineering on existing BTCUSDT data.

---

**END OF V6 EXECUTION AUDIT**
