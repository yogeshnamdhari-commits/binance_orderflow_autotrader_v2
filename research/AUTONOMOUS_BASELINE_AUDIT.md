# Autonomous Research Baseline Audit

**Generated**: 2026-08-24
**Project**: binance_orderflow_autotrader_v2

## 1. Architecture Overview

### Data Pipeline
- `app/l2_collector.py` — Binance WebSocket + REST collector
- `app/l2_replay.py` — Deterministic replay engine
- `app/orderbook.py` — Local order book reconstruction
- `app/data_quality.py` — Data integrity verification

### Feature Engineering
- `app/features.py` — Production feature engine
- `app/v3_replay.py` — V3 deterministic replay
- `app/v5_features.py` — V5 feature builder
- `app/v7_features.py` — V7 feature engineering
- `app/v7_true_features.py` — V7 true multi-level features
- `app/exp012_features.py` — EXP-012 event-level features
- `app/exp013_features.py` — EXP-013 two-stage features

### Models
- `app/v3_model.py` — Ridge regression
- `app/v5_model.py` — V5 frozen ridge
- `app/v6_model.py` — V6 MLP
- `app/v7_model.py` — V7 staged model
- `app/exp012_economic_gate.py` — Economic gate
- `app/exp013_economic_gate.py` — Two-stage gate

### Validation
- `app/walk_forward.py` — Walk-forward with purging/embargoing
- `app/experiment_registry.py` — Anti-overfitting experiment tracking

### Decision/Risk/Execution
- `app/decision.py` — Decision engine
- `app/risk.py` — Risk engine with hard limits
- `app/execution.py` — Execution engine
- `app/fillmodel.py` — Fill model

## 2. Data Sources

### V4/V5 Session Data (High-Frequency L2 Events)
- **Paths**: `data/live/v4/*/derived_v4.jsonl`, `data/live/v5/*/derived_v5.jsonl`
- **Sessions**: 21 sessions (all 2026-08-18)
- **Event Types**: `depth` (~3500/session), `trade` (~700/session)
- **Features Available**: qi_l1, mpd_bps, spread_bps, depth_slope, ofi_l1, ofi_decay,
  mlofi_weighted, cancel_pressure, log_depth, tfi_500, signed_vol_500,
  liq_depletion, full level arrays (levels_bid/levels_ask), trade_price,
  trade_qty, trade_maker
- **Critical Limitation**: All sessions are only 178 seconds long with max total
  price movement of 5.4 bps. Maximum 10s return = 3.67 bps (below 4.0 bps cost).

### Normalized AggTrades Data (730 Days)
- **Path**: `data/hist/normalized/BTCUSDT/aggTrades/*.parquet`
- **Date Range**: 2024-08-16 to 2026-08-15
- **Fields**: price, quantity, transact_time, is_buyer_maker
- **Limitation**: No order book features — only trade direction and size

### Cost Calibration
- **Taker round-trip**: 4.0146 bps
- **Maker round-trip**: 2.0 bps
- **Spread (mean)**: 0.015 bps

## 3. Experiments Conducted (13 total)

| ID | Hypothesis | Horizon | Net (bps) | Verdict |
|----|-----------|---------|-----------|---------|
| EXP-001 | V5 Ridge (OFI features) | 500ms | -1.93 | REJECTED |
| EXP-002 | V6 MLP | 500ms | -1.90 | REJECTED |
| EXP-003 | V7 Multi-Level | 500ms | -1.96 | REJECTED |
| EXP-004 | V7 Purged | 500ms | -2.00 | REJECTED |
| EXP-005/006 | V8 Direction-Magnitude | 500ms/30s | -2.50 | REJECTED |
| EXP-007 | Horizon-Matched Features | 1s-30s | -2.64 | REJECTED |
| EXP-008 | Volatility Regime | 0.5s-30s | -2.64 | REJECTED |
| EXP-009 | Order-Book Resilience | 500ms-30s | -2.40 | REJECTED |
| EXP-010 | Multi-Horizon Ensemble | 500ms-30s | -2.77 | REJECTED |
| EXP-011 | Long-Horizon (5-60min) | 5min-60min | -3.65 | REJECTED |
| EXP-012 | Aggressive Flow × Fragility | 1s-10s | -4.13 | REJECTED |
| EXP-013 | Two-Stage Event+Direction | 5min | -3.55 | REJECTED |

## 4. Terminal State

**NO_DEPLOYABLE_EDGE**: 13 experiments all rejected
**LIVE_TRADING**: HARD_BLOCKED (`V5_BASELINE_NO_LIVE_TRADE = True`)
**Terminal status**: ECONOMICALLY_IMPOSSIBLE

## 5. Key Findings

1. **Trade-sign signal**: IC = 0.01-0.15 at all horizons
2. **Book features**: IC = 0.26 for direction but V4 sessions lack large moves
3. **Trade-size amplification**: Best IC = 0.18 (p99.9 trades), dp = 1.21 bps
4. **Cost-to-signal ratio**: 5:1 to 200:1 across horizons
5. **Perfect prediction bounds**: Negative at 5s-10s, barely positive at 30s+
6. **Data incompatibility**: No dataset combines book features + large moves

## 6. Current State

- **Phase**: REJECTED (terminal)
- **Tests**: 214 passed, 1 skipped
- **No new hypotheses remain to test**
- All economically plausible research branches exhausted
