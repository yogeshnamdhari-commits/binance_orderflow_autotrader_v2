# V21 Order-Flow Algorithm — Research Specification

## Purpose

V21 is a research architecture for a causal, execution-aware Binance BTCUSDT order-flow strategy. It is not a live-trading approval and it does not replace the frozen V20 certification gate.

The design separates five questions:
1. What happened in the order book?
2. What does the current order-flow state imply about the next mid-price move?
3. How likely is a passive fill to be adversely selected?
4. Is there enough expected economic edge after fees and inventory risk to quote?
5. Could the quote actually have been passive and filled under conservative queue mechanics?

## Evidence base

- Cont, Kukanov and Stoikov document a short-horizon relationship between order-flow imbalance and price changes, with the impact depending on market depth.
- Gould and Bonart document predictive information in bid/ask queue imbalance for the direction of the next mid-price move.
- Avellaneda and Stoikov derive inventory-aware market-making quotes around a reservation price and explicitly treat inventory risk and order-arrival risk.

## Canonical event model

The authoritative event order is:

depthUpdate sequence -> reconstructed L2 state

Trades are independently ordered by (exchange_timestamp, trade_id).

Every model feature must be computed using information available at or before decision timestamp t.
Every label must use timestamps strictly after t.

No feature may use future trades, future book states, future spread, future fills, the outcome of a future quote, or data from a later validation window.

## State reconstruction

For every depth update:

best_bid, best_bid_qty, best_ask, best_ask_qty, mid, spread

are reconstructed from the L2 book.

Required integrity invariants:
- no depth sequence gaps;
- best_bid < best_ask;
- positive prices and non-negative quantities;
- every captured session must have a valid Binance snapshot bridge;
- feature timestamps must be monotonic after reconstruction;
- duplicate timestamps are allowed, but event ordering must be deterministic.

## Feature layer

### Queue state

One-level queue imbalance:

QI1 = (BidQty1 - AskQty1) / (BidQty1 + AskQty1)

Additional depth-normalized imbalance can be calculated over N levels.

### Order-flow imbalance

For each best-bid/best-ask state transition, calculate the signed OFI contribution using the standard top-of-book event formulation.

Rolling OFI is computed over fixed windows without future observations.

OFI must be normalized by contemporaneous displayed depth when used as a cross-session feature.

### Aggressive trade flow

For Binance trade events:

aggressor = BUY when m=false
aggressor = SELL when m=true

Rolling trade imbalance:

TI_w = signed_trade_qty_w / absolute_trade_qty_w

Required windows: 100 ms, 250 ms, 500 ms and 1000 ms.

Trade intensity should also be recorded in notional/second.

### Price/liquidity state

Required causal context:
- spread in bps;
- microprice displacement from mid;
- recent mid return;
- realized short-horizon volatility;
- top-level depth;
- replenishment/depletion indicators.

## Prediction target

Do not train directly on profitability.

The first alpha target is future mid-price movement at fixed horizons:

Delta_mid(t,h) = mid(t+h) - mid(t)

Required horizons: 100 ms, 250 ms, 500 ms and 1000 ms.

Both regression and directional classification should be evaluated.

A three-state target is preferred:

UP / FLAT / DOWN

where the flat band is determined from instrument tick size and the observed noise floor rather than an arbitrary zero threshold.

## Alpha model

The first production-candidate model should be deliberately simple and interpretable:

P(UP | X_t)
P(DOWN | X_t)

using a regularized probabilistic model.

Complex ML is not introduced until the simple model demonstrates stable out-of-sample incremental information.

Required metrics:
- ROC-AUC for binary directional subsets;
- multiclass log loss or Brier-style calibration metrics where applicable;
- calibration curve;
- directional accuracy;
- confidence-threshold coverage;
- performance by spread/volatility/liquidity regime.

## Toxicity model

The quote engine needs a side-specific adverse-selection estimate.

For a passive BUY:

adverse = expected_future_mid - fill_price

For a passive SELL:

adverse = fill_price - expected_future_mid

The model must estimate adverse-selection cost conditional on side, queue state, flow imbalance, recent price movement, spread, volatility, and quote distance from BBO.

Adverse selection is an execution metric, not a substitute for alpha.

## Economic edge

A quote is eligible only when expected net edge is positive after explicit costs.

For a passive BUY:

edge_buy = expected_spread_capture + expected_alpha - maker_fee - expected_adverse_selection - expected_inventory_cost

For a passive SELL:

edge_sell = expected_spread_capture - expected_alpha - maker_fee - expected_adverse_selection - expected_inventory_cost

A positive safety margin is required.

## Quote construction

The quote engine uses an inventory-aware reservation price:

reservation = mid + alpha_shift - inventory_shift

The spread component accounts for minimum economic edge, observed spread, realized volatility, toxicity and inventory risk.

### Hard passive invariant

A maker quote must satisfy:

bid <= current_best_bid
ask >= current_best_ask

after tick-size normalization.

If the requested price would cross the book, the order is suppressed, not silently converted into a different price.

A crossing request is recorded as an execution-model diagnostic.

## Inventory control

Inventory is tracked in notional terms:

inventory_fraction = inventory_notional / max_position_notional

Inventory shifts the reservation price away from the held position.

The direction must always be stabilizing:
- long inventory -> reservation price shifts downward;
- short inventory -> reservation price shifts upward.

Inventory risk must be measured independently from spread capture.

## Fill model

The deterministic passive-fill model must use observed aggressive trades.

A passive BUY can fill only when an observed aggressive SELL reaches the bid.
A passive SELL can fill only when an observed aggressive BUY reaches the ask.

Queue-ahead is initialized from displayed same-price quantity at activation.

The simulator must never fill a quote before it exists, classify a crossing order as maker, use random fills, or use future information to decide whether a historical quote would have been active.

Legacy probabilistic-fill simulation is research-only and cannot be used as certification evidence.

## P&L attribution

Every execution report must reconcile:

gross spread capture - maker/taker fees - adverse-selection cost - execution effects - inventory mark-to-market = net P&L

USD notional is authoritative. Bps versions are normalized diagnostics.

## Validation protocol

1. Data integrity — authentic Binance BTCUSDT data only.
2. Feature validity — validate feature distributions and timing.
3. Predictive validity — chronological train/validation splits.
4. Cross-session OOS — leave-one-session-out validation.
5. Execution validity — replay the fixed model against observed trades with conservative passive fills.
6. Economic validity — require positive OOS net P&L after measured costs, adequate fills and stable results across sessions.
7. Robustness — independent sessions, regime stability, parameter stability, uncertainty intervals, and multiple-testing control.

## Research anti-overfitting rules

Candidate parameters must not be selected using validation outcomes.
A common parameter set should be evaluated across independent sessions.

Any optimization search must record total configurations tested, eligibility rules, selection objective, train-only winner, untouched validation result, and parameter stability.

A model that wins training but fails OOS is a failed research result, not a live-trading candidate.

## V21 development stages

1. Implement causal feature extraction.
2. Implement fixed-horizon labels.
3. Validate feature/label timing and leakage.
4. Establish a simple probabilistic alpha baseline.
5. Measure incremental information of QI, OFI, trade flow and microprice.
6. Build a side-specific toxicity model.
7. Build an inventory-aware quote planner.
8. Enforce passive execution invariants.
9. Build deterministic event replay.
10. Perform cross-session OOS validation.
11. Only after all previous gates pass, connect to the separate production risk/execution layer.

## Safety boundary

V21 research code must keep real order submission disabled.
No research result, backtest result, or predictive metric constitutes permission to send real-money orders.

## References

1. Rama Cont, Arseniy Kukanov and Sasha Stoikov, The Price Impact of Order Book Events, Journal of Financial Econometrics, 2014. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1712822
2. Martin D. Gould and Julius Bonart, Queue Imbalance as a One-Tick-Ahead Price Predictor in a Limit Order Book, 2015. https://arxiv.org/abs/1512.03492
3. Marco Avellaneda and Sasha Stoikov, High-Frequency Trading in a Limit Order Book, Quantitative Finance, 2008. https://doi.org/10.1080/14697680701381228
4. Julius Bonart and Martin Gould, Latency and liquidity provision in a limit order book, 2015. https://arxiv.org/abs/1511.04116
