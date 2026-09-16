# V20 Controlled Testnet Runbook

## Purpose

Run the frozen V20 market-making strategy through the production execution controls using Binance USD-M Futures test infrastructure before any mainnet submission is enabled.

## Current immutable baseline

- Branch: `feature/v20-market-making`
- Strategy/config source of truth: `app/mm/config.json`
- `live_order_submission`: `false`
- Do not tune strategy parameters during this run.
- Do not store API keys or secrets in Git.

## Required environment

Set these only in the local environment:

```bash
export BINANCE_API_KEY='...'
export BINANCE_API_SECRET='...'
export BINANCE_ORDER_BASE_URL='https://<approved-binance-usdm-testnet-base>'
```

Do not commit `.env` or shell history containing credentials.

## Preflight

```bash
python3 -m compileall app tests
python3 -c "import app.mm; import app.mm.live_risk; import app.mm.reconciliation; import app.mm.execution_gateway; import app.mm.binance_execution"
python3 -m pytest -q tests/test_v20_production_controls.py
```

The production gate must report all of the following before any order submission path is considered:

- market data healthy;
- private user stream healthy;
- local/exchange orders reconciled;
- local/exchange position reconciled;
- risk gate green;
- code revision recorded;
- authoritative config SHA recorded.

## Execution sequence

1. Start market-data synchronization and wait for a valid depth snapshot plus contiguous updates.
2. Start authenticated private user-data processing.
3. Reconcile open orders and position before creating any V20 quote.
4. Keep `live_order_submission=false` during initial validation.
5. Exercise submit/cancel/partial-fill/reject/timeout/reconnect paths with the simulated exchange first.
6. Use the Binance adapter only after the local control-plane tests pass and the account is confirmed to be test infrastructure.
7. Reconcile every order update against the exchange user stream.
8. Stop new quoting immediately on data staleness, stream loss, mismatch, excessive API errors, daily-loss breach or position-limit breach.
9. At shutdown, cancel all open quotes and reconcile to a flat/known position.

## Evidence to save

For every run record:

```text
Git commit SHA
config SHA-256
capture/provenance IDs if historical replay is involved
start/end UTC timestamps
market-data reconnect count
authenticated-stream reconnect count
orders submitted
orders acknowledged
orders rejected
orders cancelled
partial fills
full fills
realized P&L
unrealized inventory MTM
fees
net P&L
max inventory
risk/kill events
reconciliation mismatches
```

## Mainnet rule

The Binance execution adapter is not itself permission to trade live. `live_order_submission=false` remains the default and the production readiness gate must pass before an explicit later deployment decision. Any market-data, private-stream, order-state or position uncertainty is a `NO_TRADE` state.
