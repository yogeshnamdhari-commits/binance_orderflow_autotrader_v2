# BTCUSDT live execution-cost calibration

- Source: cost_sampler_20260819-181615.jsonl
- Window: 1797 s, 1765 samples (1s cadence)
- Delta edge break-even reference: 2.0 bps round trip

## Measured best bid/ask spread (bps wrt mid)

| stat | value |
|---|---|
| mean | 0.015 |
| median | 0.015 |
| p90 | 0.015 |
| p99 | 0.015 |
| max | 0.674 |

Share of time spread <= 1.0 bps: **100.0%**
Share of time spread <= 1.9 bps (maker+BNB/VIP feasible): **100.0%**
Share of time spread <= 2.1 bps (delta break-even): **100.0%**

## Top-of-book depth

| metric | mean |
|---|---|
| best bid qty (USD) | 6.72 |
| best ask qty (USD) | 9.50 |
| top-5 bid depth (BTC) | 7.3385586 |
| top-5 ask depth (BTC) | 11.6024244 |
| top-5 depth imbalance (bid-ask)/(bid+ask) | 0.005151 |

## Market-order slippage by notional

| notional (USD) | buy median | buy p90 | sell median | sell p90 | depth-insufficient |
|---|---|---|---|---|---|
| 1000 | 0.0073 | 0.0073 | -0.0073 | -0.0073 | 0.1% |
| 5000 | 0.0073 | 0.0073 | -0.0073 | -0.0073 | 0.3% |
| 10000 | 0.0073 | 0.0073 | -0.0073 | -0.0073 | 0.7% |
| 25000 | 0.0073 | 0.0073 | -0.0073 | -0.0073 | 2.3% |
| 50000 | 0.0073 | 0.0073 | -0.0073 | -0.0073 | 4.0% |

## Effective taker round trip (measured slippage + 2x taker fee)

| notional (USD) | median bps | p90 bps | share <= delta break-even |
|---|---|---|---|
| 1000 | 4.015 | 4.015 | 0.0% |
| 5000 | 4.015 | 4.015 | 0.0% |
| 10000 | 4.015 | 4.015 | 0.0% |
| 25000 | 4.015 | 4.015 | 0.0% |
| 50000 | 4.015 | 4.015 | 0.0% |

## Maker view

- Rested legs pay fees only (no spread crossing): 2.00 bps round trip
- With VIP10 + BNB discount: 1.60 bps round trip
- Fill: not directly measurable from public depth-only feed; needs order-level execution log

## Verdict vs delta edge

- Measured spread (median 0.015 bps) is tick-bound and far below the delta break-even; spread is NOT the binding cost.
- Measured effective TAKER round trip at small size (median 4.0 bps) is dominated by the 2x taker fee and exceeds the ~2.0 bps delta break-even -> taker execution is not economically viable for the order-flow signal.
- MAKER execution (fees only, no spread crossing) at 2.00 bps round trip sits BELOW the 2.0 bps delta break-even when BNB/VIP discounts apply (1.60 bps), with the caveat that fill probability / adverse selection are NOT measurable from a depth-only feed.

