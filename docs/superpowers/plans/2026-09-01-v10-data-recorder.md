# V10 Data Recorder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a research-only Binance USDⓈ-M market-data recorder that preserves raw WebSocket events with local receive timestamps and validates depth sequence continuity without touching the production trading path.

**Architecture:** V10 records raw combined-stream JSON envelopes to append-only JSONL files, with one deterministic session manifest describing symbol, stream set, connection/session identifiers, and recorder clock metadata. A small pure validation layer checks depth `U/u/pu` continuity and classifies gaps, stale events, malformed events, and reconnect boundaries; the recorder never silently repairs or discards raw input. Existing `app/binance_feed.py` remains unchanged.

**Tech Stack:** Python 3, standard library (`json`, `pathlib`, `time`, `uuid`, `datetime`), existing `websocket-client`, pytest.

**Spec:** `docs/superpowers/specs/2026-09-01-v10-market-making-design.md`

## Global Constraints

- `main` remains the frozen production baseline.
- V10 code remains isolated on `research/v10-market-making-design` until all research gates pass.
- No API key is required for market-data capture.
- No live order placement is permitted.
- Raw market-data events must not be silently transformed or dropped.
- Depth sequence integrity must be explicit and auditable.
- Binance event time and local receive time must both be retained.
- Tests must be deterministic and must not require a live Binance connection.

---

### Task 1: Depth sequence validator

**Files:**
- Create: `app/v10_market_data.py`
- Test: `tests/research/test_v10_market_data.py`

**Interfaces:**
- Produces `DepthSequenceValidator`, `SequenceStatus`, `NormalizedEvent`, and `normalize_ws_event` for later recorder tasks.
- `DepthSequenceValidator.observe(event)` returns a `SequenceStatus` with `state`, `previous_u`, `current_U`, `current_u`, and `reason`.

- [ ] **Step 1: Write the failing tests**

```python
from app.v10_market_data import DepthSequenceValidator, normalize_ws_event


def test_depth_sequence_accepts_first_event_and_contiguous_updates():
    validator = DepthSequenceValidator()
    first = validator.observe({"e": "depthUpdate", "E": 1000, "U": 101, "u": 110, "pu": 100})
    second = validator.observe({"e": "depthUpdate", "E": 1100, "U": 111, "u": 120, "pu": 110})
    assert first.state == "FIRST"
    assert second.state == "CONTIGUOUS"
    assert second.previous_u == 110


def test_depth_sequence_rejects_gap_and_does_not_hide_it():
    validator = DepthSequenceValidator()
    validator.observe({"e": "depthUpdate", "E": 1000, "U": 101, "u": 110, "pu": 100})
    result = validator.observe({"e": "depthUpdate", "E": 1200, "U": 121, "u": 130, "pu": 120})
    assert result.state == "GAP"
    assert result.reason == "PU_MISMATCH"


def test_normalize_preserves_raw_payload_and_adds_receive_metadata():
    raw = '{"stream":"btcusdt@trade","data":{"e":"trade","E":123,"T":122,"p":"100.1","q":"2"}}'
    normalized = normalize_ws_event(raw, receive_ns=999)
    assert normalized.stream == "btcusdt@trade"
    assert normalized.event_type == "trade"
    assert normalized.event_time_ms == 123
    assert normalized.receive_time_ns == 999
    assert normalized.raw_json == raw
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/research/test_v10_market_data.py -q`

Expected: FAIL because `app.v10_market_data` does not yet exist.

- [ ] **Step 3: Implement the minimal validator and normalization layer**

The validator must use Binance's `pu` continuity rule when `pu` is present: after the first accepted depth event, the next event is contiguous only when `event.pu == previous_u`. It must never mutate or discard the input event. `normalize_ws_event` must preserve the exact raw JSON string and parse only the outer stream plus event metadata.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/research/test_v10_market_data.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/v10_market_data.py tests/research/test_v10_market_data.py
git commit -m "test/research: add V10 depth sequence validator"
```

### Task 2: Append-only session recorder

**Files:**
- Modify: `app/v10_market_data.py`
- Test: `tests/research/test_v10_market_data.py`

**Interfaces:**
- Produces `SessionRecorder(output_dir, symbol, streams, session_id=None)`.
- `start()` creates a session directory and manifest.
- `record_raw(raw_json, receive_ns=None)` appends one JSONL record containing the exact raw payload plus receive metadata.
- `close()` writes terminal session metadata without altering captured events.

- [ ] **Step 1: Write failing tests**

```python
import json

from app.v10_market_data import SessionRecorder


def test_session_recorder_writes_raw_event_and_manifest(tmp_path):
    recorder = SessionRecorder(tmp_path, "BTCUSDT", ["btcusdt@depth@100ms", "btcusdt@trade"])
    recorder.start(start_ns=1_000_000)
    raw = '{"stream":"btcusdt@trade","data":{"e":"trade","E":123}}'
    recorder.record_raw(raw, receive_ns=2_000_000)
    recorder.close(end_ns=3_000_000)

    session_dirs = list(tmp_path.iterdir())
    assert len(session_dirs) == 1
    manifest = json.loads((session_dirs[0] / "manifest.json").read_text())
    assert manifest["symbol"] == "BTCUSDT"
    assert manifest["start_ns"] == 1_000_000
    assert manifest["end_ns"] == 3_000_000

    rows = [json.loads(line) for line in (session_dirs[0] / "events.jsonl").read_text().splitlines()]
    assert rows[0]["raw_json"] == raw
    assert rows[0]["receive_ns"] == 2_000_000
```

- [ ] **Step 2: Run the new test and verify it fails**

Run: `pytest tests/research/test_v10_market_data.py::test_session_recorder_writes_raw_event_and_manifest -q`

Expected: FAIL because `SessionRecorder` does not yet exist.

- [ ] **Step 3: Implement the minimal append-only recorder**

Use UTF-8 JSONL with one record per input event. Flush after each event so a process interruption does not leave the final buffered event unwritten. The manifest must identify the schema version, symbol, requested streams, session ID, start/end times, and event count. Do not add credentials or API keys to any output.

- [ ] **Step 4: Run the focused test and then the full V10 test file**

Run: `pytest tests/research/test_v10_market_data.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/v10_market_data.py tests/research/test_v10_market_data.py
git commit -m "feat/research: add V10 append-only session recorder"
```

### Task 3: Binance WebSocket capture adapter

**Files:**
- Create: `app/v10_recorder.py`
- Test: `tests/research/test_v10_recorder.py`

**Interfaces:**
- Produces `V10Recorder(symbol, output_dir, ws_url, streams, clock_ns=time.time_ns)`.
- `handle_message(raw_json, receive_ns=None)` records the raw event and updates sequence diagnostics.
- `diagnostics()` returns counts for total events, depth events, trades, book-ticker events, parse errors, gaps, and reconnect boundaries.
- `build_stream_url()` produces a combined-stream URL with `timeUnit=MICROSECOND` so Binance's optional microsecond timestamp mode is explicit.

- [ ] **Step 1: Write failing adapter tests**

```python
from app.v10_recorder import V10Recorder


def test_build_stream_url_requests_microsecond_timestamps():
    recorder = V10Recorder("BTCUSDT", "/tmp/v10", "wss://fstream.binance.com/stream", ["btcusdt@depth@100ms"])
    assert "timeUnit=MICROSECOND" in recorder.build_stream_url()
    assert "btcusdt@depth@100ms" in recorder.build_stream_url()


def test_handle_message_updates_diagnostics_without_transforming_raw_event(tmp_path):
    recorder = V10Recorder("BTCUSDT", tmp_path, "wss://example.invalid/stream", ["btcusdt@depth@100ms"])
    recorder.start(start_ns=1)
    recorder.handle_message('{"stream":"btcusdt@depth@100ms","data":{"e":"depthUpdate","E":1000,"U":101,"u":110,"pu":100}}', receive_ns=2)
    recorder.handle_message('{"stream":"btcusdt@depth@100ms","data":{"e":"depthUpdate","E":1100,"U":111,"u":120,"pu":110}}', receive_ns=3)
    assert recorder.diagnostics()["depth_events"] == 2
    assert recorder.diagnostics()["gaps"] == 0
    recorder.close(end_ns=4)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/research/test_v10_recorder.py -q`

Expected: FAIL because `app.v10_recorder` does not yet exist.

- [ ] **Step 3: Implement the adapter**

Use the existing `websocket-client` dependency. The adapter must only capture public market-data streams; it must not import or call any order-placement code. On parse failure, increment a diagnostic counter and preserve the raw line in the session file with an error marker rather than silently dropping it. Sequence gaps must increment the gap counter and cause the adapter to mark the current continuity segment invalid until a new synchronization segment begins.

- [ ] **Step 4: Run the focused tests**

Run: `pytest tests/research/test_v10_recorder.py tests/research/test_v10_market_data.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/v10_recorder.py tests/research/test_v10_recorder.py
 git commit -m "feat/research: add V10 Binance market-data recorder"
```

### Task 4: Data-quality audit utility and documentation

**Files:**
- Create: `app/v10_data_audit.py`
- Test: `tests/research/test_v10_data_audit.py`
- Create: `data/research/V10_DATA_CAPTURE_PROTOCOL.md`

**Interfaces:**
- Produces `audit_session(session_dir)` returning deterministic counts and boolean gates for parse integrity, timestamp monotonicity within stream, depth continuity segments, duplicate raw records, and missing required metadata.

- [ ] **Step 1: Write failing audit tests**

```python
from app.v10_data_audit import audit_session


def test_audit_detects_depth_gap(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    (session / "manifest.json").write_text('{"schema_version":"v10.raw.v1","symbol":"BTCUSDT"}')
    (session / "events.jsonl").write_text(
        '{"stream":"btcusdt@depth@100ms","event_type":"depthUpdate","event_time_ms":1,"receive_ns":2,"raw_json":"{\\"data\\":{\\"e\\":\\"depthUpdate\\",\\"U\\":1,\\"u\\":2,\\"pu\\":0}}"}\n'
        '{"stream":"btcusdt@depth@100ms","event_type":"depthUpdate","event_time_ms":2,"receive_ns":3,"raw_json":"{\\"data\\":{\\"e\\":\\"depthUpdate\\",\\"U\\":4,\\"u\\":5,\\"pu\\":3}}"}\n'
    )
    result = audit_session(session)
    assert result["depth_gap_count"] == 1
    assert result["depth_continuity_pass"] is False
```

- [ ] **Step 2: Run to verify RED**

Run: `pytest tests/research/test_v10_data_audit.py -q`

Expected: FAIL because `app.v10_data_audit` does not yet exist.

- [ ] **Step 3: Implement deterministic audit**

The audit must never infer missing data as valid. It must report explicit failure for malformed JSON, missing required fields, receive-time regressions, duplicate raw event hashes, and depth `pu` discontinuities. Output must be JSON-serializable so it can be committed as a research artifact later.

- [ ] **Step 4: Run the complete V10 research test suite**

Run: `pytest tests/research/test_v10_market_data.py tests/research/test_v10_recorder.py tests/research/test_v10_data_audit.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/v10_data_audit.py tests/research/test_v10_data_audit.py data/research/V10_DATA_CAPTURE_PROTOCOL.md
git commit -m "research: add V10 capture data-quality audit"
```

### Verification Gate

Before declaring Phase 1 complete, run the repository's full available test suite from the actual checkout:

```bash
pytest -q
```

Also inspect `git diff --check` and confirm no V10 file imports production order-placement modules and no credentials/API keys were added. A green local test run is required before any claim that Phase 1 is complete.
