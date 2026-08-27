# FROZEN BASELINE — PHASE 1

**Date:** 2026-08-26
**Status:** Immutable reference state for all subsequent research

---

## 1. Test Suite Baseline

```
220 passed, 1 skipped in 33.73s
```

All existing tests pass. Any modification must maintain 220+ passing tests.

---

## 2. Production Path (UNCHANGED)

```
main.py entry point:
  Config → LocalOrderBook → OrderFlowEngine → EventDetector → SignalEngine → TradeOrchestrator

SignalEngine thresholds (frozen):
  BUY:  delta > 0 AND imbalance_5 > 0.20 → strength = min(1, 0.5 + imbalance_5)
  SELL: delta < 0 AND imbalance_5 < -0.20 → strength = min(1, 0.5 + |imbalance_5|)
  ABSORPTION (BUY):  imbalance_20 > 0.35 AND delta < 0
  ABSORPTION (SELL): imbalance_20 < -0.35 AND delta > 0
  Signal fires: buy > sell AND buy >= 0.9 (or symmetric for SELL)

TradeOrchestrator:
  V5_BASELINE_NO_LIVE_TRADE = True → always returns {allowed: False}
```

---

## 3. V5 Model (UNCHANGED)

```
Model: Ridge regression (alpha=0.05)
Features: 17 (ofi_l1, ofi_norm_l1, qi_l1, di_l5, di_l10, mpd_bps, spread_bps,
           bid_cancel_bps, ask_add_bps, cancel_pressure, tfi_500, liq_depletion,
           log_depth1, log_depth5, log_event_rate, depth_slope_bps, vol_500)
Primary horizon: 500ms
Calibration: 15-bin piecewise constant on validation split
Coefficients: FROZEN in data/research/v5_model.json
```

---

## 4. Feature Definitions (UNCHANGED)

```
Production features (from OrderFlowEngine.snapshot()):
  delta:              buy_volume - sell_volume over 5000ms window
  imbalance_5:        (bid_depth5 - ask_depth5) / (bid_depth5 + ask_depth5)
  imbalance_20:       (bid_depth20 - ask_depth20) / (bid_depth20 + ask_depth20)
  spread_bps:         (best_ask - best_bid) / mid * 1e4
  mid:                (best_bid + best_ask) / 2

V5 features (from derived_v5.jsonl):
  ofi_l1, ofi_norm_l1, qi_l1, di_l5, di_l10, mpd_bps, spread_bps,
  bid_cancel_bps, ask_add_bps, cancel_pressure, tfi_500, liq_depletion,
  log_depth1, log_depth5, log_event_rate, depth_slope_bps, vol_500
```

---

## 5. Execution Assumptions (UNCHANGED)

```
Taker fee (round-trip):     4.0 bps
Maker fee (round-trip):     2.0 bps
Spread (median):            0.016 bps
Slippage (p90, 1K notional): 0.008 bps
Effective taker gate:       4.016 bps (p90 measured)
Effective maker cost:       2.0 bps (fee only)
Safety margin:              0.5 bps
Total taker gate:           4.666 bps
```

---

## 6. Governance (UNCHANGED)

```
V5_BASELINE_NO_LIVE_TRADE = True (config.py:9)
TradeOrchestrator.decide() returns {allowed: False} when V5_BASELINE_NO_LIVE_TRADE=True
Config.runtime_safe() blocks live mode when V5_BASELINE_NO_LIVE_TRADE=True
Config.assert_safe() blocks live mode when LIVE_TRADING_ENABLED != true
IntegrityGate chain: BOOK_SYNCED → FEATURES_VALID → COST_VALID → SIGNAL_ALLOWED
```

---

## 7. Validated Performance Baseline

```
Production SignalEngine:
  Gross: +0.174 bps | Net (taker): -4.49 bps | Net (maker): -1.77 bps
  Sessions positive: 23/26 | t-stat: 44.76 | p < 0.0001

V5 DecisionEngine:
  Gross: +0.041 bps | Net (taker): -4.62 bps | Net (maker): -1.96 bps
  EXECUTION_READY signals: 0 (no signal passes calibrated gate)

Best preregistered conditional (TFI>0.7 & vol>p50):
  Gross: +0.762 bps | Net (taker): -3.90 bps | Net (maker): -2.18 bps

Best horizon (30s):
  Gross: +0.280 bps | Net (taker): -3.74 bps | Net (maker): -1.72 bps
  Session stability: 16/25 positive
```

---

## 8. Audit Artifacts

```
PHASE1_BASELINE.md              — Architecture map
ORDERFLOW_PRODUCTION_PATH_AUDIT.md — Production path audit
PRODUCTION_AUDIT.md             — Forensic audit
FINAL_DEPLOYMENT_AUDIT.md       — Complete 9-phase audit
EXECUTION_ECONOMIC_AUDIT.md     — Execution mechanism audit
HORIZON_ECONOMIC_AUDIT.md       — Horizon economics audit
PRE_REGISTERED_EXECUTION_HYPOTHESES.md — Execution hypotheses
PRE_REGISTERED_HORIZON_HYPOTHESES.md    — Horizon hypotheses
```

---

## 9. Data Integrity

```
Raw data: data/live/v2/<session>/raw.jsonl (immutable)
Replayed: data/live/v5/<session>/derived_v5.jsonl (deterministic)
Features: data/research/v5_evidence_features.parquet
Model: data/research/v5_model.json (frozen coefficients)
Calibration: data/research/v5_binned_calibration.json
Cost calibration: data/hist/research/execution_calibration.json
```

---

**END OF FROZEN BASELINE**
