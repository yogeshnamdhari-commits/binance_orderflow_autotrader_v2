# V5 Q2 — Contemporaneous execution cost measurement

- **Generated**: 2026-08-19T18:46:17.976137+00:00
- **Protocol**: Q2: contemporaneous execution cost measurement. Frozen V5 model is read-only; no re-fitting, no threshold changes.

## Governance

- **ORDERFLOW_BASELINE_V5 NO LIVE TRADING**: True
- Live trading is blocked until Q2 cost is measured and compared.

## Historical cost (non-contemporaneous reference)

| component | bps |
|---|---|
| taker round-trip p90 | 4.0158 |
| impact | 0.10 |
| latency | 0.05 |
| safety margin | 0.50 |
| **gate** | **4.6658** |

## Contemporaneous cost (measured live)

| component | bps |
|---|---|
| taker round-trip p90 | 4.0146 |
| spread p90 | 0.0147 |
| impact | 0.10 |
| latency | 0.05 |
| safety margin | 0.50 |
| taker total | 4.1646 |
| **gate** | **4.6646** |

## Maker cost (contemporaneous)

| component | bps |
|---|---|
| maker fee round-trip | 2.0000 |
| adverse selection | 0.7680 |
| P(fill) | 0.76 |
| non-fill reprice | 0.5000 |
| reprice component | 0.1216 |
| latency | 0.05 |
| safety margin | 0.50 |
| maker total | 2.9396 |
| **gate** | **3.4396** |

## Comparison: historical vs contemporaneous

| metric | historical | contemporaneous | diff |
|---|---|---|---|
| gate (bps) | 4.6658 | 4.6646 | -0.0012 |
| total (bps) | 4.1658 | 4.1646 | -0.0012 |

**Gate verdict**: CONTEMPORANEOUS_COST_SIMILAR

## Signal viability at contemporaneous cost

| signal gross (bps) | taker net (bps) | maker net (bps) |
|---|---|---|
| 0.0685 | -4.5961 | -3.3711 |
| 0.0801 | -4.5845 | -3.3595 |

**Viability verdict**: FAIL — net negative at all signal levels

## Cost calibration sample summary

- Samples: 1764
- Window: 1796.1 s
- Spread p90: 0.0147 bps
- Taker RT p90 (1000 USD): 4.0146
- Maker fee RT: 2.0000 bps

## Next step

- If contemporaneous gate is similar or lower than historical: Q2 confirms the historical gate was not optimistic; proceed to Q3 (contemporaneous signal expectancy measurement).
- If contemporaneous gate is materially higher: historical gate was conservative; update the measured gate and re-evaluate signal viability before any further research steps.

