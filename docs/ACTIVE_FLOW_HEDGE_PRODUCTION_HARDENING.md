# ACTIVE_FLOW_HEDGE-0.1 Production Hardening

Source strategy reference: \`a06e8f590634777bbd5ade86ef3b2563194ca2ed\`.

This branch hardens only the existing candidate. Strategy parameters are not
changed. The authoritative candidate configuration remains
\`app/mm/config_v21_active_flow_hedge_01bps.json\` and still declares
\`live_order_submission=false\`.

## Implemented hardening

- Signed Binance USDⓈ-M REST execution boundary.
- Dynamic \`exchangeInfo\` filter loading.
- Decimal tick-size and lot-size normalization.
- Post-only \`LIMIT + GTX\` submission.
- Pre-submit crossing protection.
- Projected $5,000 position-notional enforcement.
- \`AFH01-\` managed client-order namespace.
- Unknown/unmanaged order detection during reconciliation.
- Authenticated listenKey user-data stream monitor.
- Periodic REST position/order reconciliation.
- Market-data and user-stream freshness checks.
- External kill-switch file.
- Ambiguous-order-response handling with no blind retry.
- Fail-closed deployment authorization manifest.

Binance documents \`PRICE_FILTER\` and \`LOT_SIZE\` symbol rules, Futures \`GTX\`
post-only behavior, and authenticated user-data events for order and position
state.

## Authorization contract

Live authorization requires an external manifest proving:

- exact candidate config SHA-256;
- exact research reference commit;
- \`forward_certification_status=PASS\`;
- \`production_identity_status=PASS\`;
- \`execution_authorization=AUTHORIZED\`.

The manifest is deliberately absent from this branch. No code path treats
missing authorization as permission to trade.

## Strategy preservation

The registered strategy parameters remain:

- flow_quote_bias_bps = 1.0
- hedge_threshold_notional = $1,000
- hedge_ratio = 0.5
- inventory_penalty_base_bps = 1.0
- inventory_penalty_slope = 0.5 bps per 10%
- quote_size_reduction_after_breach = 50%
- max_position_notional_usd = $5,000

The existing "hedge" mechanism remains passive quote augmentation; this
execution layer does not create an independently executed hedge.

## Economic status

The immutable retrospective remains:

902 fills, -$4,517.34 realized P&L, -$16.76 net P&L, 13/21 gates,
NOT CERTIFIED, NO_DEPLOY.

Therefore this branch is execution-hardened, but it is not economically
certified for live trading.


## BTCUSDT USDⓈ-M perpetual scope

The production adapter is restricted to the registered ACTIVE_FLOW_HEDGE-0.1 candidate and BTCUSDT USDⓈ-M perpetual execution. The alpha/quote parameters are not retuned by the futures infrastructure.

Authentic research captures must contain:
- BTCUSDT USDⓈ-M depth@100ms
- BTCUSDT USDⓈ-M aggTrade
- BTCUSDT USDⓈ-M markPrice@1s
- funding-rate observations
- a valid REST depth snapshot bridged to the first depth update

Capture sequence gaps and reconnects are fail-closed for certification. Spot captures are not valid futures certification evidence.

The capture collector is scripts/capture_btcusdt_perp.py. The frozen-candidate gate is scripts/validate_afh01_btcusdt_perp.py.
