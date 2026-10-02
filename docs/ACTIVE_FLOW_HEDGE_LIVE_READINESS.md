# ACTIVE_FLOW_HEDGE-0.1 Live Readiness

This document covers execution hardening for the existing BTCUSDT USDⓈ-M perpetual
ACTIVE_FLOW_HEDGE-0.1 candidate. It does not modify the candidate parameters or
create a new alpha strategy.

## Candidate lock

- Symbol: BTCUSDT
- Market: Binance USDⓈ-M perpetual
- Frozen research reference: `a06e8f590634777bbd5ade86ef3b2563194ca2ed`
- Frozen candidate config hash: `17f9350f139c7f646f5215bf7a0dc41bcb0d79c338f2d76cc29fa33a071a97aa`
- Candidate configuration remains unchanged, including `live_order_submission: false`.

## Live execution boundary

Orders are blocked unless all of the following are true:

1. The deployment manifest exists and is internally authorized.
2. The manifest contains the exact frozen config hash and research reference.
3. Forward certification status is `PASS`.
4. Production identity status is `PASS`.
5. Execution authorization is `AUTHORIZED`.
6. The external kill-switch file is absent.
7. `AFH_LIVE_ORDERS=ARMED` is explicitly present in the runtime environment.
8. Binance exchange rules are loaded and the symbol is `TRADING`.
9. The local order book is freshly synchronized.
10. The authenticated user-data stream is healthy.
11. The BTCUSDT trade stream is healthy and fresh.
12. REST position/order reconciliation succeeds.
13. Every quote is post-only, inside the current market, and within price/quantity/notional limits.

The arming variable is deliberately separate from the frozen strategy configuration.
It is an operational execution switch and must never be persisted in the candidate config.

## Routed Binance WebSockets

The live runner uses the current routed USDⓈ-M WebSocket layout:

- Depth: `wss://fstream.binance.com/public/ws/btcusdt@depth@100ms`
- Trades + mark/funding: `wss://fstream.binance.com/market/stream?streams=btcusdt@aggTrade/btcusdt@markPrice@1s`
- User data: `wss://fstream.binance.com/private/ws/{listen_key}`

The service fails closed on a market-data or user-data WebSocket failure and requires
fresh startup synchronization before authorization.

## Operational sequence

Use a dedicated Binance Futures account/API key for this service. Keep withdrawals
disabled on the API key and do not share credentials with the research environment.

Before any live arm:

- run the offline production preflight;
- verify the exact frozen config hash;
- verify the deployment manifest;
- verify the external kill-switch path is absent;
- start the service without `AFH_LIVE_ORDERS` and confirm it remains blocked;
- only after the formal economic/forward gates are independently PASS may the operator
  set `AFH_LIVE_ORDERS=ARMED`.

Stopping or tripping the service cancels symbol orders through the existing fail-closed
execution boundary. Residual position exposure is not automatically converted into a
new hedge strategy; flattening remains an explicit operational action.

## Current research status

This hardening does not imply economic certification. The authoritative ledger remains:

- Phase 1: CLOSED, all 100ms flow candidates rejected.
- Phase 2: ORDERFLOW_ALPHA-0.1 ACTIVE.
- Deployment: NOT CERTIFIED / BLOCKED / NO_DEPLOY.
