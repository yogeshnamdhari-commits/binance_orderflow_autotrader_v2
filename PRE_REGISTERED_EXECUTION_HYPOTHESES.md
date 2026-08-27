# PRE-REGISTERED EXECUTION HYPOTHESES

**Date:** 2026-08-25
**Objective:** Determine whether the existing order-flow signal can be executed with positive net expectancy

---

## Signal Definitions (UNCHANGED)

- **Production SignalEngine:** delta > 0 & imbalance_5 > 0.20 → BUY; delta < 0 & imbalance_5 < -0.20 → SELL
- **Frozen V5:** calibrated prediction > 0 → BUY; < 0 → SELL
- **Best conditional:** TFI_abs > 0.7 & vol > p50

## Execution Cost Parameters (from execution_calibration.json, UNCHANGED)

| Parameter | Value |
|---|---|
| Taker fee (one-way) | 2.0 bps |
| Maker fee (one-way) | 1.0 bps |
| Spread (median) | 0.0157 bps |
| Slippage (p90, 1000-notional) | 0.0079 bps |
| Effective taker roundtrip (p90) | 4.0158 bps |
| P(fill) same tick (median) | 0.71 |
| Adverse selection (median) | 0.768 bps |
| Latency assumption | 5.0 ms |

---

## Hypothesis 1: Market-Order (Taker) Execution

**Description:** Fill immediately at best ask (BUY) or best bid (SELL) with taker fee.

**Mechanism:**
- BUY: fill at best_ask + slippage
- SELL: fill at best_bid - slippage
- Cost: taker_fee_roundtrip (4.0 bps) + spread + slippage
- Fill probability: 100%

**Expected cost:** ~4.03 bps roundtrip

**Predicted outcome:** Net = gross - 4.03 bps (negative for all signal types)

---

## Hypothesis 2: Aggressive-Limit Execution (Cross Spread, Then Cancel)

**Description:** Place limit order crossing the spread. If not filled within 50ms, cancel and reprice at market.

**Mechanism:**
- BUY: limit at best_ask (crossing spread by 1 tick)
- SELL: limit at best_bid (crossing spread by 1 tick)
- Wait up to 50ms for fill
- If not filled: cancel and execute at market (taker cost)
- Cost: maker fee if filled passively, taker fee if chased

**Fill model:**
- P(fill within 50ms) = f(queue_position, spread, activity)
- If filled: cost = maker_fee + half_spread
- If not filled: cost = taker_fee + full_spread + slippage

**Predicted outcome:** Slightly better than pure taker due to maker fee on partial fills

---

## Hypothesis 3: Passive-Limit (Maker) Execution

**Description:** Place limit order at best bid (BUY) or best ask (SELL). Wait for fill up to horizon (500ms). If not filled, cancel.

**Mechanism:**
- BUY: limit at best_bid (join bid queue)
- SELL: limit at best_ask (join ask queue)
- Wait up to 500ms for fill
- If not filled by horizon: cancel (no trade, no cost)
- If filled: cost = maker_fee_roundtrip (2.0 bps)

**Fill model:**
- P(fill within 500ms) = f(queue_depth, spread, activity, imbalance)
- If filled: net = gross - maker_fee (2.0 bps)
- If not filled: net = 0 (opportunity cost of missed trade)

**Predicted outcome:** Lower cost per trade but lower fill rate. Net depends on whether unfilled signals would have been profitable.

---

## Hypothesis 4: Signal-Strength-Conditioned Execution

**Description:** Use signal strength to choose between aggressive and passive execution.

**Mechanism:**
- Strong signals (strength > threshold): aggressive execution (need to capture edge)
- Weak signals (strength ≤ threshold): passive execution (save on fees)
- Threshold: pre-registered at strength ≥ 0.8 (top quartile)

**Predicted outcome:** Better than pure aggressive or pure passive alone

---

## Hypothesis 5: Queue/Imbalance-Aware Execution

**Description:** Use queue imbalance to adjust execution aggressiveness.

**Mechanism:**
- High queue imbalance (|qi_l1| > 0.7): passive more likely to fill (queue is one-sided)
- Low queue imbalance (|qi_l1| ≤ 0.3): need aggressive execution (queue is balanced, slow fill)
- Medium: mixed strategy

**Predicted outcome:** Better fill rates for passive when queue is imbalanced

---

## Hypothesis 6: Post-Only Limit with Maker Rebate

**Description:** Place post-only limit orders that earn maker rebates.

**Mechanism:**
- BUY: post-only limit at best_bid
- SELL: post-only limit at best_ask
- If order would cross spread (would take): cancel and reprice
- Cost: -maker_rebate (negative cost = income) if filled

**Note:** Binance maker rebate is typically 0.02% (2 bps) for regular users, but this varies by VIP level. We use the measured 1.0 bps maker fee from calibration.

**Predicted outcome:** Similar to Hypothesis 3 but with explicit rebate modeling

---

## Hypothesis 7: Delayed Execution (Wait for Better Fill)

**Description:** Wait X ms after signal before executing, to allow spread to normalize.

**Mechanism:**
- Wait 100ms after signal
- Then execute at market
- Rationale: immediate execution may have worse spread due to transient impact

**Predicted outcome:** May reduce spread cost but risks missing the signal edge

---

## Multiple-Hypothesis Correction

- **Number of hypotheses:** 7
- **Correction method:** Bonferroni (α = 0.05/7 = 0.00714)
- **Confidence level:** 99.286% for individual tests
- **Primary metric:** Net expectancy after execution costs

---

## Evaluation Protocol

1. Replay all 27 sessions through SignalEngine to generate signals
2. For each signal, simulate execution using historical book data
3. Compute fill price, cost, and net return for each hypothesis
4. Evaluate on chronological OOS period (sessions 212451-232919)
5. Report: gross, cost, net, fill rate, adverse selection, CI, per-session, per-regime

---

## Pre-Registered Decision Rules

- **Classification A (Viable):** Net > 0 with p < 0.00714 (Bonferroni-corrected) AND fill rate > 50%
- **Classification B (Potentially Viable):** Net > 0 with p < 0.05 (uncorrected) OR net > -1.0 bps with fill rate > 70%
- **Classification C (Insufficient):** Net < -1.0 bps OR fill rate < 50% with net < 0
