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


## FINAL RESULT — 2026-10-03

### Capture Integrity
The preregistered three-session fresh-data run completed with valid data integrity:
- Capture 1: 15,072 events; 5,886 depth; 8,585 trade; 601 mark/funding; 0 sequence gaps; 0 reconnects; BRIDGED bootstrap.
- Capture 2: 16,788 events; 5,887 depth; 10,300 trade; 601 mark/funding; 0 sequence gaps; 0 reconnects; BRIDGED bootstrap.
- Capture 3: 13,859 events; 5,886 depth; 7,372 trade; 601 mark/funding; 0 sequence gaps; 0 reconnects; BRIDGED bootstrap.

A total of 240 preregistered development candidates were tested.

### Economic Result
No candidate satisfied the preregistered gross-edge gate of >5.4 bps and positive OOS net edge.

Best pooled OOS candidate:
- Feature: `book_imbalance_10`
- Horizon: 30 seconds
- Threshold: 0.9003740724396974
- OOS observations: 720
- Gross edge: +1.2194154631 bps
- Net edge after 3.4 bps round-trip cost: -2.1805845369 bps
- Economic candidate: false

The gross-edge shortfall versus the 5.4 bps gate is 4.1805845369 bps.

### Closure
ORDERFLOW_ALPHA-0.1 is CLOSED / REJECTED on economic grounds under its preregistered information set and execution-cost assumptions.

This result does not modify or reclassify any frozen Phase 1 candidate. It also does not establish that no profitable BTCUSDT order-flow strategy exists under different information, execution, or market assumptions.

### Future Research Questions
Any further research must be registered as a new hypothesis before testing. Plausible research dimensions already identified in the ledger include:
- richer multi-level causal order-book state and state-transition features;
- cross-venue or spot/perpetual lead-lag information;
- funding, basis, open-interest, or liquidation information where authentic historical data can be obtained;
- lower-cost maker execution and queue-position modeling;
- instrument/market selection with different execution-cost-to-signal ratios.

No future hypothesis is implied or preselected by this closure entry.
