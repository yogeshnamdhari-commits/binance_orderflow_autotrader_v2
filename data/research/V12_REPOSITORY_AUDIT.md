# V12 REPOSITORY AUDIT

**Audit Date:** 2026-09-05
**Repository:** /Users/targetmobile/Downloads/binance_orderflow_autotrader_v2
**Git Branch:** research/v10-market-making-design

---

## 1. REUSABLE COMPONENTS (from V5–V11)

### Market Data Capture (REUSABLE)
- `app/v10_market_data.py` — `SessionRecorder` with v10.raw.v1 schema (events.jsonl, snapshot.json, manifest.json)
- `app/v10_capture.py` — WebSocket capture CLI (depth@100ms + aggTrade + bookTicker + REST snapshot)
- `app/v10_recorder.py` — V10 recorder extending SessionRecorder
- `app/l2_collector.py` — V2 event-level L2 collector (raw.jsonl + derived.jsonl)

### Order Book (REUSABLE)
- `app/orderbook.py` — `LocalOrderBook` with GAP/STALE detection, update-id continuity
- `app/models.py` — `TradeEvent`, `DepthEvent`, `BookState` dataclasses

### Research Pipeline (REUSABLE)
- `app/v2_*.py` — V2 research standard (features, labels, model, cost gate, signal, validation, robustness, verdict, economic report, manifest, data integrity, horizon diag, replay)
- `app/v3_*.py` — V3 pipeline (cost, model, validation, economic report, signal, replay, collector, manifest)
- `app/features.py` — V5 feature engine (17 V5_FEATURES, OrderFlowEngine)
- `app/v5_*.py` — V5 model, calibration, cost, evidence, features, run, validation

### Execution (PARTIALLY REUSABLE)
- `app/execution.py` — `OrderStateManager`, `PaperExecution`, `SimulatedExchange`
- `app/fillmodel.py` — Passive fill model
- `app/v3_cost.py` — Cost model (taker/maker gates)
- `app/cost_calibrate.py` — Empirical cost calibration
- `app/cost_sampler.py` — Walk-slippage computation

### Configuration (REUSABLE)
- `app/config.py` — Config dataclass, `V5_BASELINE_NO_LIVE_TRADE = True`
- `app/risk.py` — Risk configuration

---

## 2. MISSING PRODUCTION COMPONENTS

### Critical Missing
- **Risk Engine** — No standalone risk engine (only config in risk.py)
- **Position Engine** — No position reconciliation against exchange state
- **Order Manager** — No full lifecycle management with client/exchange IDs
- **Exit Engine** — No deterministic exit rules
- **V12 Pipeline** — No single command to run full research→validation→gate pipeline
- **Monitoring** — No operational monitoring for market data health, signal frequency, etc.
- **Audit Log** — No comprehensive audit logging for reproducibility
- **Testnet Execution** — No testnet bot
- **Production Execution** — Hard-locked, not wired
- **Reconciliation** — No exchange-vs-local reconciliation

### V12 Research
- **V12 Model** — Needs new model (not V11's gradient boosting which overfit)
- **V12 Calibration** — Needs new calibration data
- **V12 Validation** — Needs independent forward test
- **V12 Evidence Chain** — Needs complete report

---

## 3. KNOWN BUGS

### V10/V11 Fee Unit Bugs
- V10: `maker_fee_bps = -0.02` (should be +2.0), `taker_fee_bps = 0.04` (should be +5.0)
- V11: Same unit confusion in preliminary attempt
- **Status:** V10/V11 preserved as-is; V12 will use correct units

### Feature Parity Defects (V5 vs Production)
- `vol_500` hardcoded to 0.0 in production path
- `log_event_rate` uses 5000ms window in production vs 500ms in research
- Wall-clock timestamps instead of event time
- 15/17 features mismatch between research and live paths

### V9 Model Bug
- `test_treatment_metadata_records_feature_sets` fails — `'tuple' object has no attribute 'tolist'`

### V9 Features Bug
- `test_forward_labels_use_only_strictly_future_price` fails — float64 precision issue
- `test_predictors_are_lagged_and_no_future_btc_return_is_used` fails — related

---

## 4. SCIENTIFIC LIMITATIONS

### Data-Theoretic Constraint
- Maximum observed 500ms return: 3.54 bps
- Taker round-trip cost: 4.0158 bps
- Even perfect prediction cannot produce positive net expectancy
- This is NOT a modeling or data bug — it is a structural market constraint

### Unobtainable Data
- Historical open interest: FUNDAMENTALLY UNAVAILABLE (Binance API current-only)
- Liquidation events: Requires paid subscription
- Cross-venue historical: ~90 day hourly only

### Signal Magnitude
- Best observed gross: 0.762 bps (conditional, V6)
- Maker cost: 2.0 bps
- Gap: ~16x or ~5.4x below breakeven depending on execution mode

---

## 5. EXECUTION LIMITATIONS

### Live Trading
- Hard-locked: `V5_BASELINE_NO_LIVE_TRADE = True` in config.py
- `LiveExecution.submit()` raises `RuntimeError`
- `TradeOrchestrator.decide()` returns `allowed=False`

### Production Wiring
- SignalEngine produces NO BUY/SELL signals on OOS data
- TradeOrchestrator NOT wired to DecisionEngine
- Feature parity defects between research and production paths

---

## 6. DATA LIMITATIONS

### Available Data (Full 730-day coverage)
- BTCUSDT trades/order-flow: 21 GB aggTrades (millisecond resolution)
- 27 sessions of 100ms depth data
- Hourly derivatives data (too coarse for microstructure)
- BTCUSDT funding rate: 2,214 records (8h intervals)
- BTC spot/perpetual basis: 17,723 hourly records each

### Missing Data
- Historical L2 bookDepth: Binance deprecated bulk historical downloads
- Historical open interest: Current-only API
- L3 order queue position: Not available in Binance archives
- Liquidations: Paid subscription only
- Cross-venue trades: No free historical source

---

## 7. V11 DIAGNOSIS (PRESERVED)

V11 tested gradient-boosted order-flow with confidence-thresholded taker execution:
- Forward gross EV: **-0.5388 bps** (negative signal)
- Forward net EV: **-1.7116 bps** (after taker costs)
- Model predictions negatively correlated with actual returns (r=-0.0424)
- Breakeven gap: 215x below required return
- **Status: FAILED** — preserved in archive/v11/

---

## 8. RECOMMENDATION FOR V12

Given the data-theoretic constraint (max return < taker cost), V12 must test a **fundamentally different economic mechanism** that does not rely solely on order-flow price prediction:

1. **Funding rate capture + order-flow filtering** — If funding rate is sufficiently positive, the strategy can be profitable even with weak price signals, as long as the position is held through funding periods.
2. **Longer horizons** — At 30s+, the signal-to-cost ratio may improve (but prior V6 showed peak gross was 0.280 bps at 30s).
3. **Multi-asset spread** — But cross-venue data is unavailable.

V12 will test **Hypothesis 1: Funding-aware order-flow strategy** — Use order-flow signal for timing, but only enter positions when expected funding income exceeds execution costs.

---

## 9. TEST SUITE STATUS

```
3 failed, 299 passed, 1 skipped in 22.29s
```

Failures (all pre-existing, V9):
- `tests/test_v9_features.py::test_forward_labels_use_only_strictly_future_price`
- `tests/test_v9_features.py::test_predictors_are_lagged_and_no_future_btc_return_is_used`
- `tests/test_v9_models.py::test_treatment_metadata_records_feature_sets`

V10/V11 tests pass. No regressions from existing V5-V10 infrastructure.

---

## 10. COMPONENT ASSESSMENT SUMMARY

| Component | Source | Status | V12 Reuse? |
|-----------|--------|--------|------------|
| SessionRecorder | v10_market_data.py | Working | YES (data capture) |
| V10Capture CLI | v10_capture.py | Working | YES (data capture) |
| LocalOrderBook | orderbook.py | Working | YES (book engine) |
| Models | models.py | Working | YES (data models) |
| V5 Features | features.py | Working | YES (feature engine) |
| V3 Cost | v3_cost.py | Working | YES (cost model) |
| PassiveFillModel | fillmodel.py | Working | YES (fill model) |
| OrderStateManager | execution.py | Working | YES (order lifecycle) |
| Config | config.py | Working | YES (base config) |
| V2 Manifest | v2_manifest.py | Working | YES (freeze) |
| V2 Replay | l2_replay.py | Working | YES (verification) |
| RISK ENGINE | MISSING | — | NO (build new) |
| POSITION ENGINE | MISSING | — | NO (build new) |
| ORDER MANAGER | MISSING | — | NO (build new) |
| EXIT ENGINE | MISSING | — | NO (build new) |
| V12 MODEL | MISSING | — | NO (build new) |
| V12 PIPELINE | MISSING | — | NO (build new) |
| MONITORING | MISSING | — | NO (build new) |

---

**END OF REPOSITORY AUDIT**
