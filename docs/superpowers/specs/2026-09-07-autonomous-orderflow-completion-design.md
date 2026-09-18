# Autonomous Binance BTCUSDT Order-Flow AutoTrader — Completion Design

## Status
Approved architecture; implementation branch: `v15-autonomous-completion`.

## Objective
Complete the existing Binance USDⓈ-M Futures BTCUSDT order-flow system as one deterministic research-to-execution pipeline, while preserving the project's research-first controls and hard production safety gates.

The system must use authentic Binance depth/trade data, maintain a causal local order book, compute order-flow/microstructure features, generate BUY/SELL/NO-TRADE decisions, model execution economics, execute through the same event-driven interfaces in replay/paper/testnet/live modes, persist evidence, and prevent live submission unless every production gate is explicitly satisfied.

## Non-goals
- No synthetic historical L2 presented as authentic data.
- No candle-only replacement for order-flow data.
- No parameter fishing or automatic optimization against the forward/test set.
- No removal or weakening of existing validation gates merely to obtain PASS.
- No automatic enablement of real-money trading.

## Architecture

### 1. Data plane
`Binance WebSocket/REST -> normalized events -> integrity checks -> local L2 book -> feature state`

Requirements:
- sequence/timestamp validation;
- gap and stale-data detection;
- reconnect/resnapshot handling;
- deterministic event ordering;
- raw event persistence for reproducibility.

### 2. Feature plane
Causal features only. Candidate feature families already represented by the project include OFI/MLOFI, trade imbalance, Delta/CVD, microprice, depth imbalance, spread, liquidity, volatility, and microstructure-event state.

Every feature must have an explicit availability timestamp and must be computable identically during replay and live operation.

### 3. Signal plane
A versioned frozen model is loaded by hash. The model produces a directional score/probability and, where calibrated, an expected-return estimate. The signal layer never modifies model parameters while running.

Decision states remain explicit:
`NO_SIGNAL`, `INVALID_DATA`, `INSUFFICIENT_LIQUIDITY`, `HIGH_TOXICITY`, `COST_OVERWHELMED`, `POSITIVE_EXPECTANCY`, `EXECUTION_READY`.

### 4. Economic gate
Expected gross edge is converted to expected net edge using contemporaneously measured or conservatively bounded:
- exchange fees;
- spread capture/payment assumptions;
- slippage;
- adverse selection;
- latency/queue uncertainty;
- partial-fill effects.

A positive statistical signal is insufficient. A trade is eligible only when expected net edge clears the configured economic threshold and uncertainty/safety requirements.

### 5. Execution plane
A common execution interface must support:
- replay/simulation;
- paper;
- testnet;
- live (locked by default).

Order lifecycle must handle idempotency, acknowledgement, partial fills, fills, cancellation, rejection, timeout, reconciliation, restart recovery, and emergency flatten/cancel behavior.

### 6. Risk/governance plane
Hard limits include position exposure, order size, daily loss, stale data, excessive spread, API/connectivity failure, model-health failure, and emergency shutdown. Governance is fail-closed.

`LIVE_ORDER_SUBMISSION` remains hard-disabled until explicit production authorization.

### 7. Evidence plane
Each research/validation run writes machine-readable evidence containing data provenance, configuration/model hashes, feature schema, sample counts, costs, gross/net expectancy, uncertainty, regime results, and gate outcomes. Human-readable evidence-chain reports are generated from these artifacts.

## Validation chain

1. Repository/baseline audit.
2. Data provenance and integrity audit.
3. Causal/leakage audit.
4. Calibration/training using development data only.
5. Freeze model/config artifact and record hashes.
6. Independent chronological forward evaluation.
7. Execution-cost validation using realistic contemporaneous assumptions/data.
8. Regime/robustness analysis.
9. Statistical uncertainty and multiple-testing controls.
10. Paper runtime verification.
11. Testnet verification when credentials are intentionally supplied.
12. Production authorization only after all required gates pass.

A failed forward/economic/statistical gate blocks promotion; it does not trigger hidden retuning.

## Runtime data flow

`raw Binance events`
`-> normalization`
`-> integrity gate`
`-> local book/trade state`
`-> causal feature snapshot`
`-> frozen model`
`-> calibrated signal`
`-> execution-cost model`
`-> net expectancy gate`
`-> risk gate`
`-> execution adapter`
`-> order reconciliation`
`-> journal/evidence`

Replay uses the same feature, decision, risk, and execution abstractions so that live/paper/replay semantics do not diverge silently.

## Failure handling

Any of the following must fail closed to NO TRADE / safe state:
- stale or invalid market data;
- sequence gap without successful recovery;
- missing feature/model input;
- non-finite prediction;
- unavailable or stale cost calibration;
- unresolved account/order reconciliation;
- risk-limit breach;
- exchange/API uncertainty;
- process restart with unsafe unknown state.

## Testing

Tests must cover:
- event normalization and ordering;
- book reconstruction and gap recovery;
- feature causality/no future reads;
- deterministic replay;
- model artifact loading and hash verification;
- economic gate arithmetic;
- order idempotency and lifecycle transitions;
- partial fills/rejections/timeouts;
- restart/reconciliation behavior;
- risk and kill switches;
- paper/testnet/live adapter separation;
- evidence-chain completeness.

Existing tests remain authoritative; pre-existing failures must be distinguished from regressions and must not be concealed.

## Production rule

The project is considered technically complete only when the complete pipeline is executable end-to-end and its gates are enforced. It is considered economically deployable only when independent unseen data demonstrates positive net expectancy after realistic costs with adequate statistical/robustness evidence.

A technically complete but economically failed strategy remains locked from live trading.
