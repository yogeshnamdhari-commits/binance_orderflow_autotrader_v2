# V18 Information-Set Expansion Design

## Status

Approved research architecture. V16 remains the frozen control group. V17 remains rejected as an economic improvement. V18 is a research branch only; `LIVE_ORDER_SUBMISSION` remains hard-disabled.

## Goal

Test whether adding economically distinct information to the validated V16 order-flow stack can improve out-of-sample **net** expectancy after measured execution costs, without changing the validation protocol after observing results.

## Research hypotheses

1. **Higher-resolution event timing:** event-time aggregation should preserve short-lived order-flow information that fixed bars can smear.
2. **Liquidation flow:** forced-position events may provide information about transient aggressive flow and liquidity stress, but must be tested incrementally rather than assumed predictive.
3. **Funding/basis:** perpetual-vs-reference pricing and funding state may describe positioning/carry regimes and condition the short-horizon order-flow signal.
4. **Cross-market information:** BTC spot/perpetual and closely related liquid markets may lead or confirm futures microstructure; only information timestamped before the decision event is admissible.
5. **Queue-aware execution:** fill probability should be estimated from observable depth changes, trades, cancellations, spread, and order-flow pressure; unobservable exact queue position must not be fabricated.

## Information set

The V18 feature layer may consume:

- Binance USDⓈ-M depth and trade events already supported by V16.
- Binance liquidation/force-order events where an authenticated/replayable source is available.
- Funding rate, mark/index price and basis/premium observations with explicit timestamps.
- Spot/perpetual cross-market trade and top-of-book observations with synchronized timestamps.
- Existing V16 OFI, signed flow, liquidity, spread and microstructure state features.

Every feature must carry a source timestamp and an availability timestamp. Features are joined using **as-of semantics** so no future information can enter a decision.

## Existing-data constraint

The repository's audited data inventory reports BTCUSDT aggTrades, funding rates and hourly spot/perpetual data as available, but historical liquidation data and historical L2 order-book data are unavailable in the audited local inventory. Therefore:

- funding/basis and the currently available cross-market variables are treated as **ablation/control families**, not assumed sources of new edge;
- EXP-018 already found funding/basis/ETH-derived additions to have negative net expectancy and only tiny incremental predictive contribution, so V18 must not repackage those results as new evidence;
- liquidation features may be implemented and collected from Binance's live `forceOrder` market stream, but they cannot be claimed as a historical-backtest feature until a timestamped historical dataset is actually acquired;
- the historical economic gate must run only on feature families for which genuine historical data exists;
- no synthetic liquidation or reconstructed historical L2 data may be substituted.

This constraint is a stopping condition for any purported historical V18 result that requires unavailable inputs.

## Modeling

V18 retains separate models for:

1. **Return magnitude:** conditional expected signed return over a pre-registered horizon.
2. **Fill probability:** probability of execution under the selected maker/taker path.
3. **Execution cost:** spread, fees, slippage and conditional non-fill/opportunity cost.
4. **Decision engine:** trade only when expected net P&L remains positive after execution uncertainty and risk constraints.

The initial V18 model should favor interpretable, low-dimensional baselines (regularized linear/logistic models and monotonic calibration) before any deep architecture. DeepLOB-style sequence modeling is a research comparator, not an automatic production choice. DeepLOB demonstrates that temporal/spatial LOB structure can contain predictive information, but its published evidence is primarily equities, so transfer to BTCUSDT must be demonstrated empirically.

## Validation protocol

- Freeze the V16 control and all V18 feature definitions before evaluating outcomes.
- Use chronological, purged walk-forward splits.
- Maintain a completely unseen historical L2 replay set where available; if it is unavailable, mark that gate BLOCKED rather than reconstructing L2.
- Evaluate gross EV, all-in execution cost, net EV, realized simulated P&L, confidence intervals, sample size and regime-level results.
- Apply multiple-testing control to feature-family discovery.
- Run cost stress, chronological blocks, and leave-one-regime-out tests.
- Compare V18 against V16 on identical decision events where possible.
- Reject any result that depends on post-hoc horizon, threshold, feature, or cost selection.

## Economic gate

The decisive metric is **net expected value after execution**, not AUC or directional accuracy. A model with predictive AUC but negative net expectancy fails. Positive historical results are not sufficient for production authorization without independent forward/paper evidence.

## Data-quality requirements

- Event ordering and exchange sequence/update IDs must be checked where supplied.
- Clock skew and duplicate events must be detected.
- Missing intervals and reconnect gaps must be recorded.
- Cross-market timestamps must be aligned without forward filling future observations.
- Historical L2 must remain genuine exchange depth data; it must not be reconstructed from candles.

## Safety boundary

No V18 component may enable live order submission. Production authorization remains a separate explicit gate after research, historical replay, independent forward testing, paper trading and runtime reconciliation have all passed.

## Research basis

The design is grounded in established market-microstructure evidence that short-horizon price changes are related to order-flow imbalance and market depth (Cont, Kukanov & Stoikov, *Journal of Financial Econometrics*, 2014), while LOB sequence models such as DeepLOB provide a comparator for exploiting spatial and temporal book structure (Zhang, Zohren & Roberts, *IEEE Transactions on Signal Processing*, 2019). Binance's current USDⓈ-M documentation supports WebSocket market-stream subscriptions and force-order event streams; these interfaces are used only where the required historical/replay data can be obtained without violating the validation protocol.
