# V5 Q2 — Contemporaneous Execution Cost Measurement

**Generated**: 2026-08-20T00:27:40+05:30  
**Protocol**: Q2: contemporaneous execution cost measurement. Frozen V5 model is read-only; no re-fitting, no threshold changes.  
**Sample window**: 2026-08-19T18:15:58+00:00 to 2026-08-19T18:46:17+00:00 (30 minutes)  
**Instrument**: BTCUSDT perpetual (Binance USDⓈ-M Futures)  
**Notional**: 1,000 USD  
**Governance**: ORDERFLOW_BASELINE_V5 — NO LIVE TRADING

---

## Measurement Summary

| Metric | Value |
|---|---|
| Sample start UTC | 2026-08-19T18:15:58+00:00 |
| Sample end UTC | 2026-08-19T18:46:17+00:00 |
| Duration | 1,797.2 s (29.95 minutes) |
| Total observations | 1,764 |
| Sampling cadence | ~1 s |

---

## Cost Component Breakdown (bps)

| Component | p50 | p90 | p95 | p99 | Max |
|---|---|---|---|---|---|
| Spread | 0.0146 | 0.0147 | 0.0147 | 0.0147 | 0.6738 |
| Slippage (buy, 1000 USD) | 0.0073 | 0.0073 | 0.0073 | 0.0073 | 0.0073 |
| Slippage (sell, 1000 USD) | -0.0073 | -0.0073 | -0.0073 | -0.0073 | -0.0073 |
| Fee (taker, round-trip) | — | — | — | — | 4.0 |
| Fee (maker, round-trip) | — | — | — | — | 2.0 |
| Impact (allowance) | 0.10 | 0.10 | 0.10 | 0.10 | 0.10 |
| Latency | 0.05 | 0.05 | 0.05 | 0.05 | 0.05 |
| Safety margin | 0.50 | 0.50 | 0.50 | 0.50 | 0.50 |

---

## Final Gates (bps)

| Gate | Total | Gate |
|---|---|---|
| Taker (contemporaneous) | 4.1646 | **4.6646** |
| Maker (contemporaneous) | 2.9396 | **3.4396** |
| Taker (historical) | 4.1658 | **4.6658** |
| Maker (historical) | — | — |

---

## Comparison: Historical vs Contemporaneous

| Metric | Historical | Contemporaneous | Difference |
|---|---|---|---|
| Taker gate (bps) | 4.6658 | 4.6646 | -0.0012 |
| Taker total (bps) | 4.1658 | 4.1646 | -0.0012 |
| Maker gate (bps) | — | 3.4396 | — |

**Gate verdict**: CONTEMPORANEOUS_COST_SIMILAR

---

## Signal Viability at Contemporaneous Cost

| Signal Gross (bps) | Taker Net (bps) | Maker Net (bps) |
|---|---|---|
| 0.0685 | -4.5961 | -3.3711 |
| 0.0801 | -4.5845 | -3.3595 |

**Cost-to-signal ratio**: 68.1× (low) to 58.2× (high)

**Viability verdict**: FAIL — net negative at all signal levels

---

## Scientific Interpretation

1. **The contemporaneous execution cost is essentially identical to the historical cost.** The difference is -0.0012 bps (taker gate), which is negligible relative to measurement noise and market microstructure variation.

2. **The frozen V5 signal's gross expectancy (~0.07–0.08 bps) is completely overwhelmed by execution costs.** Even at the cheaper maker gate (3.4396 bps), the net is -3.36 to -3.37 bps. At the taker gate (4.6646 bps), the net is -4.58 to -4.60 bps.

3. **The cost-to-signal ratio remains extreme: 58–68×.** This confirms that the signal, as currently formulated, has no deployable economic edge under realistic execution assumptions.

4. **The measurement window was representative.** 1,764 observations over ~30 minutes at ~1-second cadence provides a stable estimate of spread and slippage for the 1,000 USD notional band. The spread was consistently tight (p90 = 0.0147 bps), and slippage was constant, indicating sufficient depth at the touch for this size.

5. **What Q2 proves**: The historical 4.6658 bps gate was not optimistic; it accurately reflects current execution costs on this instrument and notional band. The economic conclusion from the Tier-A validation is confirmed by contemporaneous measurement.

---

## Decision

**VERDICT: FAIL**

The ORDERFLOW_BASELINE_V5 frozen signal, with its ~0.07–0.08 bps gross expectancy, cannot overcome contemporaneous execution costs of ~4.66 bps (taker) or ~3.44 bps (maker). Live trading remains BLOCKED.

**Next step**: Proceed to repository-wide forensic audit and V6 design. V6 must introduce microstructure features with pre-specified economic rationale and out-of-sample validation. V5 remains the immutable baseline for side-by-side comparison. No live trading until every economic and statistical deployment gate passes.
