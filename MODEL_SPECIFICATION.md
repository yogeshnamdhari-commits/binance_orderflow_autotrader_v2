# Model Specification — V5 Frozen Ridge Model & Production Signal

## STATUS: NO_DEPLOYABLE_EDGE (Terminal)

All research has concluded. No model produces positive net expectancy after realistic costs.
See `research/FINAL_ALGO_REPORT.md` for full details.

## MODEL
- **Type**: Closed-form Ridge Regression (L2 regularized OLS)
- **Alpha**: 0.05 (predeclared, frozen)
- **Features**: 17 causal order-flow features (see FEATURES)
- **Training**: Single chronological pass on 70% earliest timestamps (18,145 rows)
- **Freeze**: Coefficients, intercept, feature means/stds saved to `v5_model.json` before any OOS evaluation
- **Governance**: `V5_BASELINE_NO_LIVE_TRADE = True` hard-coded in config; orchestrator enforces

## INPUTS
- **Data Source**: Binance BTCUSDT futures L2 depth @100ms + aggTrades
- **Collection**: `l2_collector.V2Collector` (raw JSONL) → `v4_replay` deterministic replay → `v5_features` build
- **Replay**: `v4_replay.ReplayV4` (subclasses `v3_replay.ReplayV3`) produces `derived_v5.jsonl` with per-event features
- **Timestamps**: `ts_ms` (event time from exchange, `E` field), `recv_ms` (local receipt)

## FEATURES (17, predeclared, causal)
| Feature | Source | Definition |
|---------|--------|------------|
| `ofi_l1` | `v3_replay._ofi` | CKS OFI: Σ(Δbid_qty) - Σ(Δask_qty) over changed levels in depth event |
| `ofi_norm_l1` | `v3_replay` row | `ofi_l1 / depth1` (impact per unit depth, Cont-Kukanov-Stoikov) |
| `qi_l1` | `BookStats.qi_l1` | `(best_bid_qty - best_ask_qty) / (best_bid_qty + best_ask_qty)` |
| `di_l5` | `BookStats.multi_di(5)` | Distance-weighted depth imbalance (weights 5..1) |
| `di_l10` | `BookStats.multi_di(10)` | Distance-weighted depth imbalance (weights 10..1) |
| `mpd_bps` | `BookStats.mpd_bps` | Microprice deviation from mid in bps |
| `spread_bps` | `BookState.spread_bps` | `(best_ask - best_bid) / mid * 1e4` |
| `bid_cancel_bps` | `v3_replay._cancel` | Bid cancellations in bps of mid |
| `ask_add_bps` | `v3_replay._cancel` | Ask additions in bps of mid |
| `cancel_pressure` | `v3_replay` row | `(bid_cancel + ask_cancel) / depth1` |
| `tfi_500` | `ReplayV3._flow` | Trade flow imbalance over trailing 500ms |
| `liq_depletion` | `ReplayV3._flow` | Aggressive volume / depth5 |
| `log_depth1` | `v3_replay` row | `log1p(depth1)` |
| `log_depth5` | `v3_replay` row | `log1p(depth5)` |
| `log_event_rate` | `v3_replay` row | `log1p(trade_rate)` |
| `depth_slope_bps` | `BookStats.depth_slope_bps` | Log-depth decay slope (levels 1..10) |
| `vol_500` | `v5_features.add_trailing_vol` | Realized volatility of mid log-returns over 500ms |

**Normalization**: Ridge fit standardizes features to zero mean/unit variance on TRAIN slice only (`mus`, `sds` saved in `v5_model.json`). Inference uses same `mus`, `sds`.

**Causality**: All features computed strictly from past events; `add_trailing_vol` uses only past log-returns.

## TARGET
- **Definition**: `r_h = (mid_{t+h} - mid_t) / mid_t * 1e4` (forward mid-price return in bps)
- **Horizon**: `h = 500 ms` (primary), also 250ms and 1000ms fit but not used for signal
- **Label Construction**: `v3_labels.add_labels` — finds first event with `ts_ms >= t + h`, uses its `mid`. Strictly future; NaN if no future event within horizon.
- **Units**: Basis points (bps), signed (positive = price increase)

## HORIZON
- **Primary**: 500 ms (predeclared, not optimized)
- **Alternatives**: 250 ms, 1000 ms (fit but not used for signal)

## OUTPUT
- **Model Output**: `E[r_500 | X]` in bps (continuous, magnitude + sign)
- **Prediction Units**: Basis points (bps)
- **Frozen Coefficients**: Stored in `data/research/v5_model.json` under `"500"` key

## CALIBRATION
- **Method**: Binned calibration (15 equal-width bins) on validation split (middle 15% by timestamp)
- **Calibration Set**: 3,881 finite observations (validation split, 500 ms horizon)
- **OOS Set**: 3,882 finite observations (last 15% by timestamp)
- **Mapping**: Piecewise-constant: `calibrated_return = mean(actual_return | bin(pred))`
- **Gross Calibrated Expectancy (OOS)**: +0.0797 bps
- **Maker-Adjusted**: -1.920 bps (subtracting 2.0 bps maker round-trip fee)
- **Taker-Adjusted**: -4.086 bps (subtracting 4.1658 bps taker total cost)
- **Obs > Gate**: 0.00% (gate = 4.6658 bps taker round-trip)
- **Verdict**: `CALIBRATION_VALID_BUT_NO_EDGE`

## SIGNAL RULE (Research)
- **Direction**: `sign(pred)` → LONG if `pred > 0`, SHORT if `pred < 0`
- **Threshold**: None in research (raw sign); production uses `EXECUTION_READY` gates
- **Calibration**: Binned mapping applied to raw prediction → calibrated expected return (bps)

## EXECUTION RULE (Production Decision Engine)
- **Signal**: Heuristic rule: `delta > 0 AND imbalance_5 > 0.20` → BUY; `delta < 0 AND imbalance_5 < -0.20` → SELL
- **Expected Return Source**: `fill_calib.json` condition `delta_5s_dec10_long@15s` → `gross_unconditional_bps` (-1.999 bps)
- **Cost Model**: `PassiveFillModel` (maker, 2.0 bps fee, `min_fill_prob=0.30`)
- **Gates**: Data validity → Directional signal → Liquidity → Toxicity → Net edge > 0 & fill prob ≥ 0.30
- **Decision States**: `NO_SIGNAL`, `INVALID_DATA`, `INSUFFICIENT_LIQUIDITY`, `HIGH_TOXICITY`, `COST_OVERWHELMED`, `EXECUTION_READY`
- **Horizon**: 15,000 ms (15 s) — **different from research 500 ms**

## COST MODEL
| Component | Value (bps) | Source |
|-----------|-------------|--------|
| Maker fee (round-trip) | 2.0 | `execution_calibration.json` |
| Taker fee (round-trip) | 4.0 | `execution_calibration.json` |
| Taker spread p90 | ~0.3 | Measured |
| Taker slippage p90 (1000 USD) | ~0.5 | Measured |
| Impact allowance | 0.10 | Predeclared |
| Latency cost | 0.05 | Predeclared |
| Conservatism margin | 0.50 | Predeclared |
| **Taker Gate (total)** | **4.6658** | `v5_cost.measured_gate()` |
| **Maker Gate (fee + margin)** | **2.5** | `v3_cost.maker_cost_bps()` + 0.5 |

**Mismatch**: Research validation uses taker gate (4.67 bps); production signal is maker (2.0 bps fee). Actual fill calibration shows unconditional gross -1.999 bps → net after maker fee ≈ -4.0 bps.

## KNOWN LIMITATIONS
1. **Signal/Model Disconnect**: Research V5 model (500ms) never gates production execution (15s heuristic).
2. **Negative Production Edge**: Fill calibration shows negative unconditional gross expectancy for the production signal (-2.0 bps).
3. **No Statistical Gate**: No confidence interval on net expectancy; `EXECUTION_READY` requires only pointwise `net > 0`.
4. **OFI Aggregation Ambiguity**: Production `features.py` uses per-event level deltas only; research uses full-book diffs.
4. **MLOFI Aliasing**: `f.mlofi = f.ofi` (not a true multi-level OFI).
5. **Condition/Signal Mismatch**: Decision engine condition `delta_5s_dec10_long` vs `_raw_direction` threshold `imbalance_5 > 0.20` not verified aligned.
6. **Cost-Style Mismatch**: Research validation uses taker gate (4.67 bps); production is maker (2.0 bps).
6. **No Statistical Significance Gate**: No CI/bootstrap on net expectancy.
7. **Cost Calibration Mislabel**: `pct_spread_le_1_5` uses threshold 1.1 bps (label says 1.5).