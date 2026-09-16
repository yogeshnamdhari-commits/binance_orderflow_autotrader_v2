# V12 RESEARCH BASIS

## Economic Hypothesis

**H12: Funding-aware order-flow strategy on BTCUSDT perpetual futures can produce positive net expected value.**

### Rationale

V5-V11 research conclusively established that pure order-flow price prediction (500ms horizon) is economically insufficient:
- Best observed gross edge: 0.174–0.762 bps
- Taker round-trip cost: 4.0158 bps
- Maker cost: 2.0 bps
- Maximum observed single-event return: 3.54 bps < cost floor

The fundamental constraint is that the order-flow signal magnitude (≤ ~1 bps) cannot overcome Binance BTCUSDT execution costs (2-4 bps).

### New Economic Mechanism

V12 tests whether **funding rate income** can bridge the execution cost gap:

```
Expected Net EV = (Signal Edge + Expected Funding Income) - Execution Costs
```

Where:
- **Signal Edge**: Order-flow prediction (same as V5-V11, ≤ ~1 bps)
- **Expected Funding Income**: BTCUSDT perpetual futures pay/n Receive funding every 8 hours
- **Execution Costs**: Taker fees (5 bps) + slippage + adverse selection + latency

### Mechanism Details

1. **Signal**: Use the frozen V3 ridge model (AUC ~0.666) to predict 500ms direction
2. **Funding Filter**: Only enter positions when the 8-hour implied funding rate exceeds a threshold
3. **Direction**: Trade in the direction predicted by the signal
4. **Holding Period**: Hold through at least one funding period (8 hours) to capture funding
5. **Exit**: Exit when signal reverses OR target/stoploss hit OR funding period expires without sufficient edge

### Economic Calculation

```
Breakeven: Signal_Edge + Funding_Income = Execution_Cost + Exit_Cost
```

If:
- Signal Edge = 0.17 bps (V5 baseline, conservative)
- Execution Cost = 5.0 bps (entering) + 5.0 bps (exiting) = 10.0 bps round-trip
- Funding Income required = 9.83 bps per 8-hour period

Binance BTCUSDT funding rates historically range from -0.01% to +0.1% per 8-hour period.
At the high end (+0.1% = 10 bps), funding could theoretically cover costs.

But: the signal must be directionally correct for the FULL holding period, not just the entry direction. If the price moves against the position, the loss could exceed funding income.

### Testable Prediction

**If** the average 8-hour funding rate when the V12 signal fires is positive AND exceeds the execution cost, THEN the strategy has positive expected value.

**If not**, V12 FAILS, confirming the structural constraint.

### Literature Basis

1. **Funding rates and perp pricing**:
   - Krause, K. (2021). "The Economics of Perpetual Futures Markets"
   - Binance Futures documentation: funding occurs every 8 hours at 00:00, 08:00, 16:00 UTC

2. **Order-flow prediction**:
   - Cont, Kukanov & Stoikov (2014). "Price impact of order book events"
   - Easley, Lopez de Prado & O'Hara (2012). "Flow toxicity and liquidity"

3. **Transaction costs**:
   - Hendershott, Jones & Menkveld (2009). "Call market liquidity"
   - Binance fee schedule: maker 0.02%, taker 0.05%

### Data Requirements

V12 needs:
- 100ms depth data (for order-flow features)
- Trade data (for signed volume)
- Funding rates (every 8 hours, from Binance API)
- Mark price (for position valuation)
- Entry/exit prices (for execution cost measurement)

### Pre-registered Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Signal horizon | 500ms | Matches V5 baseline |
| Funding threshold | 5.0 bps per 8h | Must cover round-trip costs |
| Max holding | 16h | Two funding periods |
| Position size | 0.01 BTC | Small, manageable |
| Taker fee | 5.0 bps | Binance standard |
| Maker fee | 2.0 bps | Binance standard |
| Slippage | 0.5 bps | Conservative |
| Stop loss | 50 bps | Risk management |
| Take profit | 50 bps | Risk management |

### Why This Is A New Experiment (Not V11 Retry)

V11 tested "confidence-thresholded gradient-boosted taker execution" — a pure price prediction strategy. V12 tests "funding-aware order-flow" — a strategy where the economic mechanism includes FUNDING INCOME as a revenue stream, not just price prediction.

The funding mechanism provides an additional, theoretically positive revenue stream that V11 did not test. If funding rates are sufficiently positive when the signal fires, the combined edge could overcome execution costs.

### Expected Outcome

Given the historical data audit findings:
- Funding rates: 2,214 records acquired (8h intervals, 730 days)
- Average funding rate: ~0.01% (1 bps) per 8h period
- This is below the breakeven threshold (9.83 bps)
- **Prediction: V12 will FAIL** — funding income is insufficient to cover costs

But V12 must be tested to confirm this prediction with proper methodology.

---

**END OF V12 RESEARCH BASIS**
