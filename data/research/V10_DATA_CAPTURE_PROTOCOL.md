# V10 Data Capture Protocol

**Status:** Research-only. No order placement.

## Scope

V10 begins with public Binance USDⓈ-M market-data capture. The capture layer is intentionally separated from `app/binance_feed.py` and all production execution modules.

## Streams

Initial BTCUSDT capture uses:

- `btcusdt@depth@100ms` — diff-depth updates
- `btcusdt@trade` — individual trade events
- `btcusdt@bookTicker` — best bid/ask diagnostics

The recorder requests `timeUnit=MICROSECOND` explicitly. Binance documents optional microsecond timestamp support for WebSocket streams; event payloads therefore retain exchange timestamps at the connection's selected resolution.

## Raw-data rule

Every received WebSocket message is preserved as an exact `raw_json` string. The recorder may add local metadata such as `receive_ns`, parsed stream name, and event type, but it must never silently rewrite or discard an input event.

Malformed JSON is preserved with a `parse_error` field so later audits can distinguish an invalid message from an absent message.

## Depth integrity

For diff-depth events, the validator records the Binance update identifiers `U`, `u`, and `pu` without modifying the source payload. After the first event in a continuity segment, a subsequent event is accepted as contiguous only when its `pu` equals the previous event's `u` and its update range is ordered.

A gap starts a failed continuity segment. Reconnection creates a new segment and is explicitly counted; a reconnect does not retroactively make the previous segment valid.

This follows Binance's documented diff-depth sequencing model and is necessary before any order-book replay or queue-position research is trusted.

## Session layout

Each capture session is stored as:

```text
<output>/<session_id>/
  manifest.json
  events.jsonl
```

`manifest.json` contains the V10 raw schema version, symbol, requested streams, session identifier, start/end local timestamps, and event count.

Each JSONL event contains:

- `receive_ns`
- `stream`
- `event_type`
- `event_time_ms`
- `raw_json`
- optional `parse_error`

## Audit gates

A captured session is not research-valid until the deterministic audit reports:

1. JSON/row parse integrity PASS
2. required metadata PASS
3. local receive-time monotonicity PASS within each stream
4. exchange event-time monotonicity PASS within each stream
5. duplicate raw-event count = 0
6. depth continuity PASS

A failed gate is evidence that the capture cannot yet be used for deterministic replay. It is not repaired by interpolation, silent deletion, or parameter changes.

## Authoritative Binance references

- Binance USDⓈ-M Futures WebSocket market-stream documentation: https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams
- Binance derivatives API change log: https://developers.binance.com/docs/derivatives/change-log
- Binance USDⓈ-M Futures REST market-data documentation: https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api

## Deployment restriction

This protocol contains no trading credentials and no order-placement capability. V10 remains research-only until deterministic replay, execution economics, walk-forward OOS validation, robustness testing, and the project's deployment gate have independently passed.
