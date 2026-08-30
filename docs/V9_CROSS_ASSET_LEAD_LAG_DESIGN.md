# V9 Cross-Asset Lead-Lag Research Design

**Status:** APPROVED / RESEARCH-ONLY
**Date:** 2026-08-31

## Objective
Test whether information available from BTCUSDT at time t adds robust, economically executable predictive information for returns of a fixed basket of liquid Binance USDⓈ-M altcoin perpetuals over 5–15 minute horizons.

## Scope
- Leader: BTCUSDT perpetual.
- Followers: exactly 10 liquid Binance USDⓈ-M altcoin perpetuals selected by a pre-specified historical-liquidity rule.
- Primary horizon: 5 minutes.
- Secondary horizons: 10 and 15 minutes.
- The basket is fixed before final out-of-sample evaluation and is not selected using future returns.

## Information Set
Candidate BTC information is restricted to information causally available at t:
1. lagged BTC returns;
2. BTC order-flow variables where valid historical event/order-book data exists;
3. BTC derivatives variables where sufficiently granular, timestamp-aligned historical data exists.

Each follower model also contains its own lagged return controls. A BTC-augmented model is evaluated against an altcoin-only control so that ordinary follower autocorrelation is not misidentified as BTC lead-lag information.

## Statistical Models
Primary model family: regularized logistic regression for directional prediction.

- Control: altcoin-only information.
- Treatment: altcoin controls + BTC information.

The treatment is evaluated for incremental out-of-sample predictive value. No unrestricted model/feature search is permitted after OOS results are observed.

## Causality and Labels
For each follower and timestamp t, all predictors must be known by t. Forward return labels use only prices after t. Timestamp synchronization, missing data, duplicate events, and overlapping labels must be explicitly handled. Purging/embargo is required wherever training and evaluation observations can share future-label information.

## Economic Evaluation
The final economic gate uses measured, instrument-specific execution costs rather than a fixed assumed 2.5 bps cost. Costs must include applicable fees, spread, slippage/market impact, and funding where relevant. Gross and net expectancy are reported separately with uncertainty intervals.

Statistical significance alone is insufficient. The V9 hypothesis must demonstrate robust positive net executable expectancy out of sample.

## Validation
- Chronological train/validation/test separation.
- Purged/embargoed validation where required by label overlap.
- Walk-forward evaluation.
- Asset-by-asset and aggregate results.
- Multiple-testing control across assets and horizons.
- Stability across time/regimes.
- No parameter selection using final OOS observations.

## Deployment Rule
V9 remains research-only and cannot remove the existing live-trading hard block. Only a separately reviewed result satisfying statistical, economic, robustness, execution, and risk gates may be considered for paper trading and subsequently live deployment.

## Preservation Rule
V5–V8 research artifacts and negative findings are immutable controls for this experiment. V9 must not modify, overwrite, or reinterpret those results.
