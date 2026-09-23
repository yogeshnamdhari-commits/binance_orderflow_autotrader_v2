# V20 Minimum Production Execution Design

**Date:** 2026-09-16
**Branch:** `feature/v20-market-making`
**Base revision:** `9a43c4e61538a7aab374ac65079a8b44cf506116`

## Goal

Move the V20 order-flow market-making system from historical replay toward a production-capable execution architecture while keeping real-money order submission explicitly disabled until paper/testnet execution, reconciliation, and safety gates pass.

## Scope

The production path will preserve the existing V20 signal/quote logic and authoritative `app/mm/config.json` while adding a controlled execution boundary around it.

The minimum path is:

```text
Live Binance market data
        ↓
Order-book / order-flow state
        ↓
V20 quote engine
        ↓
Order manager
        ↓
Binance execution endpoint
        ↓
Private user-data stream
        ↓
Order / position reconciliation
        ↓
Risk + kill-switch governance
```

No strategy optimization is part of this work. No profitability claim is part of this work.

## Components

### 1. Live market-data adapter

Consume current Binance USDⓈ-M market depth/trade data using the supported WebSocket architecture. Normalize messages into the existing V20 market-state/event interfaces. Detect stale data, sequence gaps, malformed messages, disconnects, and reconnects.

### 2. Order manager

Own client order identifiers, submission state, acknowledgement, partial fills, full fills, cancellation, replacement, rejection, timeout, and idempotency. No duplicate order may be created from a retry without an explicit new client order ID and state transition.

### 3. Private account stream

Consume authenticated user-data events for order, execution, balance, and position changes. Treat exchange-confirmed state as authoritative for reconciliation.

### 4. Reconciliation

Continuously compare local order/position state against exchange state. Any mismatch blocks new quoting and invokes the configured recovery/kill procedure.

### 5. Risk controls

Hard limits must include maximum position, maximum notional, maximum order quantity, maximum open orders, stale-quote timeout, maximum data latency, daily loss limit, API error limit, and position mismatch kill switch.

All safety checks fail closed to `NO_TRADE`.

### 6. P&L and inventory

Track realized P&L, unrealized inventory mark-to-market, fees, and execution costs separately and provide a single reconciled net P&L view. Historical V20 backtest accounting remains distinct from live account accounting.

### 7. Test execution mode

Provide an execution mode that exercises the complete order lifecycle without enabling real-money trading. It must use the same order-state, reconciliation, and risk code paths as production wherever possible.

### 8. Live-order gate

`live_order_submission` remains `false` by default. Enabling real order submission requires explicit configuration plus all prerequisite readiness checks passing. A failed prerequisite must prevent order submission.

## Failure Handling

The system must stop opening new exposure when any of the following occurs:

- market-data disconnect or unacceptable staleness
- detected sequence/data integrity problem
- private stream disconnect
- order acknowledgement timeout
- order-state mismatch
- position mismatch
- risk-limit breach
- excessive API errors or rate-limit failures
- stale quotes
- unrecognized execution response
- configuration/provenance mismatch

Recovery must be deterministic and must reconcile with exchange state before resuming quotes.

## Testing Strategy

1. Unit-test market-data normalization and stale/gap detection.
2. Unit-test order-state transitions and idempotency.
3. Unit-test reconciliation with matching and mismatching exchange states.
4. Unit-test every risk/kill-switch condition.
5. Run integration tests through a simulated exchange/event stream.
6. Run the complete path in paper/testnet mode with real-time Binance data.
7. Verify fills, cancellations, partial fills, position, fees, and P&L against exchange-reported state.
8. Keep real-money submission disabled until every required execution and reconciliation test passes.

## Explicit Non-Goals

- No parameter optimization.
- No claim of positive expectancy from historical results.
- No automatic enabling of live-money trading.
- No storage of API secrets in Git.
- No commitment of large raw market-event files to ordinary Git.

## Acceptance Criteria

The execution subsystem is ready for the next controlled deployment stage only when:

- all tests pass;
- order lifecycle state is deterministic;
- exchange and local positions reconcile;
- disconnect/reconnect recovery is tested;
- risk controls fail closed;
- P&L includes realized and inventory MTM effects;
- the exact configuration and code revision are recorded for each run; and
- `live_order_submission` remains disabled until an explicit deployment decision is made after testnet/paper validation.
