# V10 Capture Runbook

V10 is research-only. The capture process uses Binance public USDⓈ-M WebSocket market data and contains no API-key or order-placement path.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Capture BTCUSDT

From the repository root:

```bash
PYTHONPATH=. python -m app.v10_capture --symbol BTCUSDT --duration 60s --output data/v10
```

Longer sessions can be requested with `m` or `h`, for example `30m` or `2h`.

Each session is written locally as:

```text
data/v10/<session_id>/
  manifest.json
  events.jsonl
```

The raw WebSocket message is preserved in `raw_json`; local receive time is stored separately from the exchange event timestamp.

## Required validation before replay

Do not feed a capture into the V10 replay/economic pipeline until the capture audit reports PASS for:

1. JSON/row parse integrity
2. required metadata
3. receive-time monotonicity within stream
4. exchange-time monotonicity within stream
5. duplicate raw events = 0
6. depth sequence continuity

Any failed interval remains invalid. Do not interpolate, silently delete, or repair it with future information.

## Research sequence

```text
capture
  -> audit
  -> deterministic book replay
  -> queue-state reconstruction
  -> fill calibration (TRAIN only)
  -> adverse-selection/markout measurement
  -> passive-order economics
  -> chronological walk-forward OOS
  -> robustness + statistical gates
  -> final decision
```

A positive backtest result alone does not authorize live trading. The V10 deployment state remains gated until the complete economic protocol passes.
