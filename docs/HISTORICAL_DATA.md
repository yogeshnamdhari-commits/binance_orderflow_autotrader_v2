# Historical data plan — status: availability + integrity audit COMPLETE

Ref: `https://github.com/binance/binance-public-data` (official), endpoint `https://data.binance.vision`.

## Audit results (run 2026-08-16, BTCUSDT USD-M futures)

Window 2024-08-16 .. 2026-08-15 (730 days).

| type | coverage | integrity (sampled) |
|---|---|---|
| aggTrades | 730/730 available, no interior gaps | 53/53 sampled days SHA256-verified against `.CHECKSUM`; 0 id gaps, 0 duplicates, 0 out-of-order |
| trades | 730/730 available | not part of replay core |
| metrics | 730/730 available | catalogued |
| bookDepth | 730/730 files exist | NOT L2: it is the depth-at-+/-%-from-mid metric (timestamp,percentage,depth,notional) |

## Historical L2 (T_DEPTH) — NOT CLAIMED

Binance publishes no tick-by-tick L2 order-book history in the public archives.
Historical L2 is a separate facility: access-granted, <7-day request ranges, can
contain gaps; its coverage cannot be claimed until that access is obtained and
audited. No L2 is reconstructed from candles. Days without authentic L2 are
explicitly marked unavailable; L2-dependent features (imbalance, OFI) are gated
on authentic L2 and recorded as unavailable rather than synthesized.

## Tooling

- `python -m app.hist.audit --symbol BTCUSDT` — availability (full window) + integrity/gap audit + normalization to `data/hist/`.
  `--sample-every N` controls the integrity sample step; `--reuse-availability` skips re-probing.
- `python -m app.hist.replay --symbol BTCUSDT --start YYYY-MM-DD --end YYYY-MM-DD` — event replay of verified days;
  trade-flow buckets and day summaries are journaled to `data/hist/replay/journal.jsonl`.

## Process

inventory -> download -> `.CHECKSUM` (SHA256) verify -> content gap audit -> normalize to parquet
(`data/hist/normalized/{SYMBOL}/aggTrades/…`) -> 2-year availability report (`data/hist/report.md`)
-> event replay -> order-flow research on authentic periods only.

Replay core uses aggregate trades (Binance `/fapi/v1/aggTrades` lineage). The remaining work
(full 2-year download, T_DEPTH access, L2-gated research) is tracked in the build gates.