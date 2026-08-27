# V7 FINAL DECISION

**Date:** 2026-08-27
**Objective:** Determine whether information arriving in another BTC market/venue predicts subsequent Binance BTCUSDT move strongly enough to overcome realistic execution costs
**Classification:** **D = DATA INSUFFICIENT FOR V7**

---

## SUMMARY

V7 (cross-market price discovery) cannot be tested because the required data is not available.

| Information Source | Available | Usable? |
|---|---|---|
| Coinbase BTC/USD | NO | — |
| Kraken BTC/USD | NO | — |
| Bybit BTCUSDT | NO | — |
| OKX BTCUSDT | NO | — |
| CME BTC futures | NO | — |
| Liquidation data | NO | — |
| Perp/Spot basis | Hourly only | Too coarse |

---

## AVAILABLE DATA

Only Binance BTCUSDT data is available:
- 21 GB of aggTrades (per-trade, millisecond resolution)
- 27 sessions of 100ms depth data
- Hourly derivatives data (too coarse)

---

## HYPOTHESES STATUS

| ID | Hypothesis | Status |
|---|---|---|
| H1 | Cross-Venue Lead-Lag Returns | UNTESTABLE |
| H2 | Information Share | UNTESTABLE |
| H3 | Cross-Venue Price Dislocation | UNTESTABLE |
| H4 | Cross-Venue Order Flow Divergence | UNTESTABLE |
| H5 | Perp-Spot Basis Lead | UNTESTABLE (too coarse) |
| H6 | Liquidation Pressure | UNTESTABLE |

---

## ECONOMIC GAP REMAINS

| Configuration | Gross (bps) | Net (maker) |
|---|---|---|
| V5 baseline | 0.174 | -1.826 |
| V6 best | 0.120 | -2.438 |
| V7 | UNTESTABLE | — |

---

## CONCLUSION

V7 cannot be tested with available data. The BTCUSDT order-flow information set, even when augmented with all research-backed microstructure variables, does not contain enough predictive information to produce economically viable trading signals.

To achieve viability, the following would be required:
1. **Cross-venue historical data** (Coinbase, Kraken, Bybit, OKX)
2. **Liquidation data** (paid subscription)
3. **Higher-frequency derivatives data** (sub-minute)

---

## RECOMMENDATION

1. **Do NOT modify production V5**
2. **Keep V5_BASELINE_NO_LIVE_TRADE = True**
3. **Live trading remains BLOCKED**
4. **V7 is complete — no further action possible without additional data**

---

**END OF V7 FINAL DECISION**
