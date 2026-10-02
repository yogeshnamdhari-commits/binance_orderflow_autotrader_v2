# ORDERFLOW_ALPHA-0.1

## Purpose
Discover a BTCUSDT USDⓈ-M perpetual order-flow signal with gross edge large enough to
survive preregistered execution costs, rather than tuning any frozen candidate.

## Scope
- Instrument: BTCUSDT USDⓈ-M perpetual only
- Data: fresh authentic Binance depth@100ms + aggTrade + mark/funding capture
- Horizons: 250ms, 500ms, 1s, 2s, 5s, 10s, 30s, 60s
- Candidate features:
  - signed trade-flow imbalance
  - L2 book imbalance at 1/5/10 levels
  - microprice displacement
  - depth replenishment/depletion
  - trade intensity
  - flow × volatility interaction
- No live order submission.

## Preregistered Economic Gate
Published research gate:
- one-way taker cost basis: 1.7 bps
- round-trip taker cost: 3.4 bps
- safety buffer: 2.0 bps
- minimum gross-edge gate: **> 5.4 bps**

The 5.4 bps figure is a research gate. It does not assert that 5.4 bps of alpha
exists. Any change to the cost basis requires a documented amendment before results
are interpreted.

## Validation Design
1. Capture three independent fresh sessions.
2. Capture 1 is development-only for candidate/rule selection.
3. Captures 2 and 3 are untouched OOS validation.
4. Forward labels are constructed strictly from future mid-prices; features use only
   information available at the observation timestamp.
5. Candidate rules are finite and preregistered: feature sign plus training-quantile
   tail thresholds.
6. Report per-session and pooled gross edge, net edge after 3.4 bps round-trip cost,
   safety-buffer margin, sample count, and block-bootstrap confidence intervals.
7. A candidate is economically promising only when OOS gross edge exceeds 5.4 bps
   and the corresponding OOS net edge remains positive. No live certification follows
   from this scan alone.

## Stop Conditions
- Any capture with a sequence gap, reconnect, or unbridged bootstrap is invalid.
- No frozen candidate/config is modified.
- No live execution is enabled.
- A negative OOS result closes the corresponding rule; it is not tuned on OOS data.
