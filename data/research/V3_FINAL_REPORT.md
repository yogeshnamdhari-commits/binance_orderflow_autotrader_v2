# V3 Final Report — Execution-Aware Microstructure Model on BTCUSDT

## Decision: STOP (as designed)

The frozen V3 model, applied to the **untouched OOS slice**, produces a tiny
positive gross move signal but far below the **measured** execution cost +
predeclared safety margin. The protocol's stop rule fires: no re-fitting, no
rescue, no parameter changes. STOP is recorded in `v3_oos.json` and
`V3_ECONOMIC_REPORT.json` (verdict FAIL per v2_verdict criteria).

## Why STOP (the economics)

| quantity | value |
|---|---|
| OOS rows (last 15% chronological) | 3,889 |
| gross move expectancy (label × sign) | **+0.074 bps** |
| taker gate (measured rt 4.016 + impact 0.10 + latency 0.05 + margin 0.50) | **4.666 bps** |
| net taker expectancy | **−4.591 bps** |
| net maker expectancy (measured drag/fill) | −2.977 bps |
| decision states under cost gate | LONG 0 / SHORT 0 / NO_TRADE 3,889 |

A round trip costs ~4.17 bps of real fees+slippage; the signal moves prices by
~0.07 bps on average. The gap is two orders of magnitude. Every OOS trade is
economically negative — NO_TRADE for all 3,889 rows.

## Protocol integrity (predeclared, then frozen, then measured)

1. Feature stack declared in `app/v3_features.py` (ofi, imbalance, depth slope,
   trade-flow, cancel pressure, depletion…) — no additions after OOS.
2. Ridge OLS, alpha=0.05, fit **once** on the chronological 70% train slice
   (25,922 derived rows / 12 immutable live sessions). r2_train ≈ 0.25 (labels
   are heavily overlapped 250/500/1000 ms forward moves).
3. Cost inputs **measured**, not assumed: taker p90 rt 4.166 bps from
   `execution_cost_model.json`; maker fill/adverse-selection from
   `fill_calib.json` (73-day calibrated p_fill per state); frozen in
   `v3_cost_calibration.json`.
4. Freeze manifest `V3_OOS_MANIFEST.json` — **freeze_id `0d0e4291…`** — hashes
   15 modules + 3 artifacts + dependencies. Reproducible (re-frozen to the same
   id). OOS read only after the freeze.
5. Untouched-OOS scoreboard (`v3_oos.json`) + economic report
   (`V3_ECONOMIC_REPORT.json`) consume the frozen artifacts; nothing fed back.

## Deliverables (data/research)

- `v3_model.json` / `v3_calibration.json` — frozen ridge (coefs, means/stds, r2)
- `v3_cost_calibration.json`, `v3_features.parquet` (25,922×30)
- `V3_OOS_MANIFEST.json` — freeze_id `0d0e4291880bee7ce6b69478455386a11e451360f1dad6d6a9344d8944544b5d`
- `v3_oos.json`, `V3_ECONOMIC_REPORT.json` — OOS scoreboard + verdict FAIL/STOP
- `tests/test_v3.py` — 6 tests, all green (determinism, strict labels, model
  freeze determinism, cost-gate margins/states, report E2E, manifest freeze)

## Note on the data

These 12 sessions are short, captured sandbox/free-market clips (~25.9k events,
best-tick depth 1–2 BTC). An edge this close to the cost line is expected to be
economically dead at $1k notional. To revive V3: (a) longer sessions with full
5-level depth under real latency, (b) larger notional bands where maker fill
economics shift, (c) passive-maker execution whose adverse selection is already
measured in `fill_calib.json`. STOP is the honest, protocol-compliant outcome.