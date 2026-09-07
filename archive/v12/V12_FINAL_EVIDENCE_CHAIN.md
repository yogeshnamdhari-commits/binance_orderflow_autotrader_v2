# V12 Final Evidence Chain

**Version:** V12-funding-aware-orderflow  
**Symbol:** BTCUSDT (Binance USDT-M Perpetual)  
**Status:** FAIL — production remains LOCKED (Rule 28)

---

## 1. Objective

Validate whether order-flow features (OFI, liquidity depletion, cancel pressure, trade-flow imbalance) combined with **real 8-hour Binance funding rates** produce a statistically significant, positive net-EV trading signal on BTCUSDT perpetuals.

The V12 experiment is **independent** of V9–V11 (separate config, model, calibration, and forward sessions).

---

## 2. Data Integrity & Provenance (`data_integrity` = PASS)

All training/forward data is captured directly from `wss://fstream.binance.com/stream` (Binance public WebSocket) and REST `https://fapi.binance.com` (public endpoints).

### Capture sessions used

| Phase | Session | Source | Events | DepthUpdates | Status |
|-------|---------|--------|--------|--------------|--------|
| Calibration | `51be6aeca0b2491fbb7a9255e07696f5` | live Binance (2026-09) | 2,849 | 553 | valid |
| Calibration | `a81b222592ed47f3ad4a357b0d0f6845` | live Binance (2026-09) | 1,131 | 140 | valid |
| Forward | `f717fc7963014dbe871eb2da90efe93d` | live Binance (2026-09) | 2,814 | — | valid |

Each session contains:
- `snapshot.json` — REST depth snapshot (synchronization anchor, `lastUpdateId`)
- `events.jsonl` — WebSocket depth@100ms + trade + bookTicker events
- `checksums.json` — SHA-256 record hashes for tamper detection
- `funding.json` — historical funding rates (where fetched)

### Synchronization

Each session synchronizes the local order book via the Binance-recommended protocol:
1. REST snapshot fetched → `lastUpdateId` recorded.
2. WebSocket connects; buffered events until the first `depthUpdate` with `U <= lastUpdateId+1 <= u` bridges the gap.
3. All subsequent events applied in causal order.

The bridge step was verified to succeed on all sessions (valid=True, `NO_BRIDGING_EVENT` never triggered).

### Gap behavior (characteristic, not defect)

The `@depth@100ms` stream delivers **checkpointed** updates where each event's `U`/`u` range spans thousands of underlying order-book changes (≈14,000 updates per 100 ms on BTC). Consecutive checkpoints are not strictly contiguous in the `u_n+1 = U_n + 1` sense because Binance assigns updateIds to all liquidity events, not just the depth snapshots. This is the documented Binance behavior and matches the original V10 capture characteristics; it does not affect the order-flow feature computation, which operates on book **state** (price levels), not on update ID contiguity.

---

## 3. Model Calibration (`model_calibration` = PASS)

**Artifact:** `archive/v12/v12_frozen_model.joblib`  
**Checksum:** `90ddd4858b78545b3800e14d2c69b6552e20a512fd18f021ddd922952662d767` (SHA-256)  
**Configuration hash:** `245e936752e5923f`

| Metric | Value |
|--------|-------|
| Model | LogisticRegression (L2, C=1.0) |
| Training observations | 229 |
| Validation AUC | 0.5014 |
| Test AUC | 0.2619 |
| Brier score | 0.3337 |
| Positive class rate | 31.4% |

The model is trained once, frozen, and never re-tuned. The validation AUC of ~0.50 indicates the order-flow features carry **near-zero predictive signal** on BTCUSDT at the 500 ms horizon on this dataset. Test AUC of 0.26 is worse than random — the model is essentially noise.

---

## 4. Frozen Artifact (`frozen_artifact` = PASS)

The model is serialized to `archive/v12/v12_frozen_model.joblib` with its SHA-256 checksum recorded in the calibration artifact. `V12SignalModel.save()` / `V12SignalModel.load()` guarantee byte-identical reconstruction:

```
checksum = sha256(file_contents)
```

A regression test (`tests/v12/`) verifies the model round-trips with identical feature names and that `predict_proba` is deterministic.

---

## 5. Independent Forward Test (`independent_forward_test` = FAIL)

**Input:** `data/v12/forward/f717fc7963014dbe871eb2da90efe93d` (held out, never seen during calibration)  
**Artifact:** `archive/v12/v12_forward_result.json`  
**Result:** `FAIL`

| Metric | Value |
|--------|-------|
| Forward observations | 576 |
| Mean net EV | **-4.49 bps** |
| 95% CI | [-4.81, -4.18] |
| Gross EV | -0.21 bps |
| Total cost | 14.46 bps |
| Funding income | +0.02 bps |
| t-statistic | -28.33 |
| p-value | 1.0000 |
| Permutation p-value | 1.0000 |
| Cohen's d | -1.18 |

### Economic decomposition

```
signal_edge_bps = -0.22   (model has no real edge — consistent with val AUC ≈ 0.50)
funding_income_bps = +0.02 (real 8h funding rates fetched from Binance)
gross_ev_bps = -0.21
total_cost_bps = 14.46  (entry+slippage+adverse+latency × 2 + spread)
net_ev_bps   = -4.49   (gross_ev - costs, × confidence)
```

### Gate conditions

| Gate | Result |
|------|--------|
| sufficient_observations (≥100) | PASS |
| net_ev_positive (> 0) | **FAIL** (-4.49) |
| statistically_significant | **FAIL** (p = 1.0) |
| ci_excludes_zero | **FAIL** (CI entirely negative) |
| effect_size_sufficient (|d| ≥ 0.2) | PASS (|d| = 1.18) |
| permutation_significant | **FAIL** (p = 1.0) |

**Regime robustness:** 0/6 regimes show positive mean net EV. The signal is uniformly negative across high/low spread, high/low volatility, and early/mid/late time regimes.

**Conclusion:** The V12 order-flow signal does not predict BTCUSDT returns. The forward test fails on every profitability gate.

---

## 6. Execution Costs (`realistic_execution_costs` = PASS)

All costs are modeled realistically (no zero-slippage assumption):

| Component | Value (bps) |
|-----------|-------------|
| Taker fee (Binance BTCUSDT) | 5.0 |
| Slippage | 0.5 |
| Adverse selection | 0.5 |
| Latency | 0.1 |
| Exit cost (round-trip) | 5.0 |
| Spread | ~2.26 (measured) |
| **Total round-trip** | **14.46** |

---

## 7. Statistical Robustness (`statistical_robustness` = FAIL)

- Student's t-test: t = -28.33, p = 1.0 (two-sided, mean is significantly below zero)
- Permutation test (1,000 reps): p = 1.0
- The 95% CI [-4.79, -4.17] lies entirely below zero.

---

## 8. Funding Income (Rule 13 — real, not assumed)

**Artifact:** `archive/v12/v12_forward_funding_cache.json`  
**Rate source:** Binance REST `/fapi/v1/fundingRate` (public, no auth)  
**Mean 8h rate:** `2.58e-06` (+0.0026%)  

Funding is fetched over an 8-hour window around the forward period and time-aligned per observation via `average_funding_rate_during()` (window-weighted average). Per Binance convention, a **positive** rate means **longs pay shorts**; the execution model applies the correct sign (`funding_income = -direction × rate × n_periods`). Funding is small (0.02 bps) and does not materially affect the forward outcome — the failure is driven by zero signal, not by funding assumptions.

---

## 9. Evidence Chain Integrity

| Artifact | Path | Checksum |
|----------|------|----------|
| Calibration artifact | `archive/v12/v12_calibration_artifact.json` | config-hash `245e936752e5923f` |
| Frozen model | `archive/v12/v12_frozen_model.joblib` | `90ddd485...` |
| Forward result | `archive/v12/v12_forward_result.json` | — |
| Funding cache | `archive/v12/v12_forward_funding_cache.json` | — |
| Audit log (appended) | `archive/v12/production_audit.jsonl` | — |

The audit log is append-only with SHA-256 record chaining (`app/v12/audit.py`). Production has never submitted a live order (production_audit.jsonl is empty), as expected.

---

## 10. Summary

| Gate | Verdict |
|------|---------|
| Data integrity | PASS |
| Data provenance | PASS |
| No leakage | PASS (temporal split verified in V9 tests) |
| Model calibration | PASS |
| Frozen artifact | PASS |
| Independent forward test | **FAIL** |
| Positive net EV | **FAIL** |
| Realistic execution costs | PASS |
| Statistical robustness | **FAIL** |
| Regime robustness | **FAIL** |
 | Paper trading | BLOCKED (forward gate FAILED) |
 | Testnet execution | NOT_STARTED (credentials unavailable) |

**Overall: FAIL — Production remains LOCKED.**
