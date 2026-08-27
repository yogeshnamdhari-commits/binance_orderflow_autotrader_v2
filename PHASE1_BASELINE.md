# PHASE 1 — REPOSITORY BASELINE: Architecture Map

## 1.1 Directory Structure

```
binance_orderflow_autotrader_v2/
├── app/
│   ├── main.py                    # Live entry point
│   ├── config.py                  # Configuration + V5_BASELINE_NO_LIVE_TRADE=True
│   ├── orderbook.py               # LocalOrderBook (imbalance, microprice, depth)
│   ├── features.py                # OrderFlowEngine (live features)
│   ├── events.py                  # EventDetector (threshold-based)
│   ├── signal.py                  # SignalEngine (rule-based)
│   ├── decision.py                # DecisionEngine (V5 model + calibration)
│   ├── orchestrator.py            # TradeOrchestrator (governance block)
│   ├── risk.py                    # RiskEngine (pre-trade controls)
│   ├── integrity_gate.py          # IntegrityGate (book→features→cost→signal)
│   ├── execution.py               # PaperExecution, SimulatedExchange
│   ├── fillmodel.py               # PassiveFillModel (maker execution)
│   ├── binance_feed.py            # WebSocket market data feed
│   ├── l2_collector.py            # Event-level L2 collector
│   ├── l2_replay.py               # Deterministic replay
│   ├── journal.py                 # Persistent audit trail
│   ├── reconciliation.py          # Order/position reconciliation
│   ├── v3_replay.py               # V3 feature computation
│   ├── v4_replay.py               # V4 execution-layer view
│   ├── v5_model.py                # Frozen V5 ridge model
│   ├── v5_features.py             # V5 feature definitions (17 features)
│   ├── v5_calibration.py          # Binned calibration
│   ├── v5_cost.py                 # Measured cost gate (4.6658 bps)
│   ├── v3_cost.py                 # V3 cost model components
│   ├── v3_labels.py               # Label computation
│   ├── v3_model.py                # V3 model (ridge estimator)
│   ├── v5_evidence.py             # V5 OOS evaluation
│   ├── paper_runtime.py           # Paper trading engine
│   └── [v2_v8_*.py, exp*.py]      # Research/experiment modules
├── data/
│   ├── research/
│   │   ├── v5_model.json          # Frozen V5 model (17 features, 500ms)
│   │   ├── v5_binned_calibration.json
│   │   ├── v5_evidence_features.parquet
│   │   └── hist/research/
│   │       └── execution_calibration.json
│   └── live/
│       ├── v2/                    # Raw collected sessions
│       └── v5/                    # Replayed sessions with V5 features
├── tests/                         # 220 tests
├── run_paper_simulation.py        # Paper trading simulation
└── backtest_production.py         # Production SignalEngine backtest
```

## 1.2 Component Dependency Map

```
main.py
  ├── config.Config
  ├── config.V5_BASELINE_NO_LIVE_TRADE
  ├── orderbook.LocalOrderBook
  ├── features.OrderFlowEngine
  ├── events.EventDetector
  ├── signal.SignalEngine
  ├── orchestrator.TradeOrchestrator
  ├── integrity_gate.IntegrityGate
  ├── binance_feed.BinanceMarketFeed
  └── journal.Journal

OrderFlowEngine (features.py)
  ├── orderbook.LocalOrderBook
  └── FlowFeatures dataclass

EventDetector.detect(f) → MicroEvents
  ├── f.delta (buy-sell volume over 5000ms)
  ├── f.imbalance_5 (book imbalance at 5 levels)
  └── f.imbalance_20 (book imbalance at 20 levels)

SignalEngine.decide(f, events) → Signal
  ├── Event strengths (0.5 + imbalance_5 for flow, 0.6 for absorption)
  └── Threshold: strength >= 0.9

DecisionEngine.evaluate(f) → SignalDecision
  ├── v5_model.predict() (17 features)
  ├── v5_calibration.calibrate_prediction()
  ├── v5_cost.measured_gate() (4.6658 bps)
  ├── fillmodel.PassiveFillModel
  └── Gate: calibrated > 5.1658 bps

TradeOrchestrator.decide() → dict
  └── V5_BASELINE_NO_LIVE_TRADE → always {allowed: False}

PaperExecution.submit() → ExecutionResult
  └── Fill at touched price (buy@ask, sell@bid)

RiskEngine.pre_trade() → RiskDecision
  ├── daily_loss_limit, spread_limit, max_exposure
  ├── portfolio_heat, max_drawdown, stale_data
  ├── connection_guard, rejection_cooldown
  └── inverse-fractional position sizing

IntegrityGate.evaluate() → dict
  └── BOOK_SYNCED → FEATURES_VALID → COST_VALID → SIGNAL_ALLOWED
```

## 1.3 Data Flow

```
Binance WebSocket
  → binance_feed.on_message()
    → DepthEvent → book.apply() → flow.on_book_event()
    → TradeEvent → flow.on_trade()
      → flow.snapshot() → FlowFeatures
        → detector.detect() → MicroEvents
          → signals.decide() → Signal(BUY/SELL/NO_TRADE)
            → orch.decide() → always blocked
```

## 1.4 Key Constants

| Constant | Value | Source |
|---|---|---|
| V5_BASELINE_NO_LIVE_TRADE | True | config.py:9 |
| Measured cost gate | 4.6658 bps | v5_cost.py |
| DecisionEngine gate | 5.1658 bps | decision.py:249 |
| Safety margin | 0.5 bps | v3_cost.py:29 |
| V5 alpha | 0.05 | v5_model.py:23 |
| V5 horizon | 500ms | v5_model.py:24 |
| V5 features | 17 | v5_features.py |
| SignalEngine threshold | 0.9 | signal.py:8-9 |
| EventDetector imbalance_5 | ±0.20 | events.py:8-9 |
| EventDetector imbalance_20 | ±0.35 | events.py:10-11 |
| Trade window | 5000ms | features.py:116 |
| TFI window | 500ms | features.py:295 |

## 1.5 Frozen V5 Model Summary

- **Type**: Ridge regression (alpha=0.05)
- **Features**: 17 (ofi_l1, ofi_norm_l1, qi_l1, di_l5, di_l10, mpd_bps, spread_bps, bid_cancel_bps, ask_add_bps, cancel_pressure, tfi_500, liq_depletion, log_depth1, log_depth5, log_event_rate, depth_slope_bps, vol_500)
- **Top coefficients**: qi_l1 (1.995), mpd_bps (-1.928), di_l10 (-1.914), di_l5 (1.882)
- **R² train**: 0.261
- **N train**: 18,118
- **Calibration**: 15-bin piecewise constant on validation split

## 1.6 Execution Cost Decomposition

| Component | Value | Source |
|---|---|---|
| Effective taker roundtrip (p90) | 4.0158 bps | execution_calibration.json |
| Market impact allowance | 0.10 bps | v3_cost.py:30 |
| Latency cost | 0.05 bps | v3_cost.py:31 |
| Safety margin | 0.50 bps | v3_cost.py:29 |
| **Total gate** | **4.6658 bps** | v5_cost.py |
| Maker fee round-trip | 2.0 bps | execution_calibration.json |
| Taker fee round-trip | 4.0 bps | execution_calibration.json |
| Spread (median) | 0.0157 bps | execution_calibration.json |
| Slippage (p90, 1000-notional) | 0.0079 bps | execution_calibration.json |

## 1.7 Test Coverage

- 220 tests passing, 1 skipped
- Coverage: feature parity, decision engine, governance block, replay engine, integration, safety
