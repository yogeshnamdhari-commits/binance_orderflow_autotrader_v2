# Build gates
1. Data: exchange metadata, depth synchronization, sequence-gap detection, stale-data checks.
2. Research: authentic L2 inventory, trade inventory, checksums, gap/coverage report, normalized event schema.
3. Strategy: independently tested features/events, no look-ahead or future leakage.
4. Backtest: fees, slippage, latency assumptions, chronological splits, untouched test, trade attribution.
5. Execution: exchange filters, authenticated lifecycle, partial fills, unknown-status recovery, user-stream reconciliation, restart recovery.
6. Deployment: paper -> testnet -> controlled live. Live stays OFF until every gate passes.
