# V14 — Pre-Registered Protocol

## Experiment Design
- **Version**: V14-orderflow-10s-maker-taker (config_hash: 12e0e1775ee6b46d)
- **Symbol**: BTCUSDT (Binance USD-M Futures)
- **Horizon**: 10 seconds (signal_horizon_ms=10000)
- **Rationale**: V13 proved order-flow signal exists at 2s (AUC 0.72) but 2s price moves (~1bps) are too small to overcome taker execution costs (14.52 bps). V14 tests whether a longer horizon (10s, ~5-10bps moves) combined with passive maker execution (cost floor ~1.6bps) produces positive net EV.

## Hypothesis
At a 10-second prediction horizon, BTCUSDT order-flow features (book imbalance, aggressive trade imbalance, microprice deviation, depth pressure, regime state) combined with passive maker-queue execution will produce statistically significant positive net EV after fees/rebates/slippage/adverse selection.

## Key Design Decisions (pre-registered, NOT selected by result)
1. Horizon = 10s — chosen A PRIORI for economic viability, not because it maximizes AUC
2. Maker/taker execution model — entry 75%% maker (-2bps rebate) / 25%% taker (+5bps fee)
3. Total roundtrip cost = 1.6bps (breakeven threshold for signal)
4. Feature set = 10 features (NOT a zoo, all economically motivated)
5. Model = LogisticRegression (same as V13, not re-tuned)
6. Time-series split: train 70%% / val 15%% / test 15%% (sequential, no shuffle)

## Data Contamination Rules (ENFORCED)
- V14 calibration uses ONLY data/v14/calibration/
- V13 forward data (6270a46...) is EXCLUDED
- V13 calibration data is EXCLUDED
- V12 data is EXCLUDED
- Forward capture must start AFTER calibration ends

## Acceptance Thresholds
- Forward net EV > 0
- 95%% CI lower bound > 0
- p-value < 0.05 (permutation + t-test)
- >= 4/6 regimes positive
- ALL gates PASS → paper trading enabled
- FAIL on any gate → LIVE stays locked
