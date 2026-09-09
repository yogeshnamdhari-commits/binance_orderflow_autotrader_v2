# V16 Production Runbook

## Current state

V16 research and paper-trading evidence are preserved. Production is fail-closed.
`LIVE_TRADING_ENABLED` defaults to `false` and the repository governance lock
`ORDERFLOW_BASELINE_V5_NO_LIVE_TRADE` defaults to `true`.

## Required preflight

1. Run the complete V16/V17 test suite.
2. Run `python -m app.v17.preflight`.
3. Verify the frozen V16 model and configuration checksums.
4. Verify that the realized paper-trading artifact is non-empty and matches the
   independently generated paper-trading evidence. Do not reconstruct realized
   trades from summary statistics.
5. Verify market-data freshness, symbol, position limits, daily-loss limit,
   spread limit, and kill-switch state.
6. Verify authenticated Binance order lifecycle reconciliation before enabling
   any real submission.

## Live execution safety

The `app.binance_execution.BinanceFuturesExecution` adapter is fail-closed. Real
submission requires all of the following simultaneously:

- valid API key and secret supplied through environment variables;
- `LIVE_TRADING_ENABLED=true` at runtime;
- repository governance lock explicitly disabled;
- higher-level production preflight already passed.

Credentials must never be committed to Git or written to logs.

## Deployment boundary

The repository can provide and test the execution adapter, but a real-money
activation cannot be certified from GitHub alone. It requires the operator's
live Binance account, credentials, exchange permissions, and a controlled
production run. Until those external conditions are verified, production must
remain locked.

## No bypass

Never manufacture missing paper-trade records, convert model-predicted P&L into
realized P&L, or change economic thresholds after observing forward results.
If any required artifact or gate is missing, the correct state is `LOCKED`.
