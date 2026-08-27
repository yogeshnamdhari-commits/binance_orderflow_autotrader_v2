"""Deterministic research-vs-live feature parity test.

Feeds identical raw Binance events into:
  A. Research pipeline (ReplayV4 → ReplayV3._row() → derived row per event)
  B. Live pipeline (OrderFlowEngine.snapshot() per event, using event time as now_ms)

Compares every V5 model feature event-by-event and scores both with the frozen
V5 model to quantify prediction divergence.

Usage:
  python3 tests/test_feature_parity.py [session_dir] [--events N]
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, '.')

from app.v4_replay import ReplayV4
from app.orderbook import LocalOrderBook
from app.features import OrderFlowEngine, V5_FEATURES
from app.models import DepthEvent, TradeEvent
from app.v5_features import add_trailing_vol, COLUMNS
from app.v5_model import load_model, predict

MODEL_PATH = Path("data/research/v5_model.json")


def load_raw_events(session_dir):
    events = []
    with open(session_dir / "raw.jsonl") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def run_research_pipeline(events, session_name="test"):
    """Run ReplayV4 on raw events, return DataFrame with V5 features + vol_500."""
    rp = ReplayV4(log=lambda *_: None)
    for ev in events:
        rp.feed_line(json.dumps(ev))

    df = pd.DataFrame(rp.rows)
    df["session"] = session_name
    for f in V5_FEATURES:
        if f not in df.columns:
            df[f] = 0.0
    cols = [c for c in COLUMNS if c in df.columns]
    df = df[cols].reset_index(drop=True)
    df = add_trailing_vol(df, windows=(500,))
    return df


def run_live_pipeline(events):
    """Run OrderFlowEngine on the same raw events, using event time as now_ms."""
    book = LocalOrderBook(50)
    flow = OrderFlowEngine(book, window_ms=5000)
    rows = []

    for ev in events:
        kind = ev["kind"]
        if kind == "snapshot":
            book.load_snapshot(ev["bids"], ev["asks"], ev["last_update_id"])
            flow.prev_full_bids = dict(book.state.bids)
            flow.prev_full_asks = dict(book.state.asks)
        elif kind == "depth":
            e = DepthEvent(
                int(ev["E"]), int(ev["U"]), int(ev["u"]),
                [(float(p), float(q)) for p, q in ev["bids"]],
                [(float(p), float(q)) for p, q in ev["asks"]])
            book.apply(e)
            flow.on_book_event(e)
            f = flow.snapshot(now_ms=ev["E"])
            rows.append(f)
        elif kind == "trade":
            tid = int(ev.get("a", ev.get("t", 0)))
            t = TradeEvent(int(ev["T"]), tid,
                           float(ev["p"]), float(ev["q"]), bool(ev["m"]))
            flow.on_trade(t)
            f = flow.snapshot(now_ms=ev["T"])
            rows.append(f)
        elif kind == "bookTicker":
            pass

    return rows


def safe_float(v):
    if v is None:
        return 0.0
    try:
        v = float(v)
        return v if np.isfinite(v) else 0.0
    except (TypeError, ValueError):
        return 0.0


def compare_all_features(research_df, live_rows, n_events):
    n = min(len(research_df), len(live_rows), n_events)
    results = []
    for feat in V5_FEATURES:
        mismatches = 0
        max_abs_diff = 0.0
        sum_abs_diff = 0.0
        examples = []

        for i in range(n):
            r_val = safe_float(research_df.iloc[i].get(feat, 0.0))
            l_val = safe_float(getattr(live_rows[i], feat, 0.0))
            diff = abs(r_val - l_val)
            if diff > 1e-9:
                mismatches += 1
                max_abs_diff = max(max_abs_diff, diff)
                sum_abs_diff += diff
                if len(examples) < 3:
                    examples.append((i, r_val, l_val, diff))

        mean_abs_diff = sum_abs_diff / mismatches if mismatches > 0 else 0.0
        results.append({
            "feature": feat,
            "mismatches": mismatches,
            "total": n,
            "mismatch_pct": mismatches / n * 100 if n > 0 else 0.0,
            "max_abs_diff": max_abs_diff,
            "mean_abs_diff": mean_abs_diff,
            "examples": examples,
        })
    return results, n


def compare_predictions(research_df, live_rows, n_events, model_path=MODEL_PATH):
    n = min(len(research_df), len(live_rows), n_events)
    model_d = load_model(model_path)

    r_feats = research_df[V5_FEATURES].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    r_pred = predict(model_d, r_feats, 500)

    live_data = []
    for i in range(n):
        live_data.append([safe_float(getattr(live_rows[i], f, 0.0)) for f in V5_FEATURES])
    l_feats = pd.DataFrame(live_data, columns=V5_FEATURES).fillna(0.0)
    l_pred = predict(model_d, l_feats, 500)

    mismatches = 0
    max_diff = 0.0
    sum_diff = 0.0
    for i in range(n):
        diff = abs(float(r_pred[i]) - float(l_pred[i]))
        if diff > 1e-9:
            mismatches += 1
            max_diff = max(max_diff, diff)
            sum_diff += diff
    mean_diff = sum_diff / mismatches if mismatches > 0 else 0.0

    return {
        "mismatches": mismatches, "total": n,
        "max_abs_diff": max_diff, "mean_abs_diff": mean_diff,
        "r_pred_range": (float(np.min(r_pred)), float(np.max(r_pred))),
        "l_pred_range": (float(np.min(l_pred)), float(np.max(l_pred))),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session_dir", type=Path, nargs="?",
                     default=Path("data/live/v2/20260818-191124"))
    ap.add_argument("--events", type=int, default=1000)
    ap.add_argument("--multi-session", action="store_true",
                     help="Run across all sessions for larger sample")
    a = ap.parse_args()

    print("=" * 95)
    print("RESEARCH-LIVE FEATURE PARITY TEST")
    print("=" * 95)

    if a.multi_session:
        session_dirs = sorted(Path("data/live/v2").glob("2026*"))
        session_dirs = [sd for sd in session_dirs if (sd / "raw.jsonl").exists()]
        print(f"Sessions: {len(session_dirs)}")
    else:
        session_dirs = [a.session_dir]
        print(f"Session: {a.session_dir}")

    all_research_dfs = []
    all_live_rows = []
    total_events = 0

    for sd in session_dirs:
        events = load_raw_events(sd)
        depth_n = sum(1 for e in events if e["kind"] == "depth")
        trade_n = sum(1 for e in events if e["kind"] == "trade")
        snap_n = sum(1 for e in events if e["kind"] == "snapshot")
        print(f"\n  {sd.name}: raw={len(events)} (snap={snap_n}, depth={depth_n}, trade={trade_n})")

        rdf = run_research_pipeline(events, sd.name)
        lrows = run_live_pipeline(events)

        all_research_dfs.append(rdf)
        all_live_rows.extend(lrows)
        total_events += len(rdf)

    if len(all_research_dfs) > 1:
        research_df = pd.concat(all_research_dfs, ignore_index=True)
    else:
        research_df = all_research_dfs[0]

    live_rows = all_live_rows
    n = min(len(research_df), len(live_rows), a.events)

    print(f"\nTotal research rows: {len(research_df)}")
    print(f"Total live rows:     {len(live_rows)}")
    print(f"Comparing first {n} events...")

    # --- Feature comparison ---
    results, n = compare_all_features(research_df, live_rows, n)

    print()
    print("-" * 95)
    print("FEATURE PARITY RESULTS")
    print("-" * 95)
    print(f"{'Feature':22s} {'Status':8s} {'Mismatches':>12s} {'MaxDiff':>14s} {'MeanDiff':>14s}")
    print("-" * 95)

    for r in results:
        status = "PASS" if r["mismatches"] == 0 else "FAIL"
        print(f"{r['feature']:22s} {status:8s} {r['mismatches']:12d} "
              f"{r['max_abs_diff']:14.8f} {r['mean_abs_diff']:14.8f}")

    # --- Prediction comparison ---
    print()
    print("-" * 95)
    print("PREDICTION PARITY (frozen V5 model)")
    print("-" * 95)
    try:
        pred = compare_predictions(research_df, live_rows, n, MODEL_PATH)
        pred_status = "PASS" if pred["mismatches"] == 0 else "FAIL"
        print(f"{'Predictions':22s} {pred_status:8s} {pred['mismatches']:12d} "
              f"{pred['max_abs_diff']:14.8f} {pred['mean_abs_diff']:14.8f}")
        print(f"  Research pred range: [{pred['r_pred_range'][0]:.6f}, {pred['r_pred_range'][1]:.6f}]")
        print(f"  Live pred range:     [{pred['l_pred_range'][0]:.6f}, {pred['l_pred_range'][1]:.6f}]")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"  Error: {e}")

    # --- Summary ---
    print()
    print("=" * 95)
    failed = sum(1 for r in results if r["mismatches"] > 0)
    total = len(results)
    print(f"SUMMARY: {total - failed}/{total} features match")
    print("=" * 95)

    # Print detailed root cause analysis (for any FAILED features)
    print()
    print("ROOT CAUSE ANALYSIS FOR EACH FAILED FEATURE:")
    print("-" * 95)
    causes = {
        "ofi_l1": "TRADE EVENTS: research=0.0, live=retains last depth OFI",
        "ofi_norm_l1": "Rounding (research: round(,6), live: no round) + ofi_l1 trade issue",
        "qi_l1": "Rounding (research: round(,6), live: no round). Diff ~1e-7. NOT MATERIAL",
        "di_l5": "Rounding (research: round(,6), live: no round). Diff ~5e-7. NOT MATERIAL",
        "di_l10": "Rounding (research: round(,6), live: no round). Diff ~5e-7. NOT MATERIAL",
        "mpd_bps": "Rounding (research: round(,6), live: no round). Diff ~3e-7. NOT MATERIAL",
        "spread_bps": "Rounding (research: round(,4), live: no round). Diff ~1e-8. NOT MATERIAL",
        "bid_cancel_bps": "DIFFERENT FORMULA: research=cancel_qty/mid*1e4 (per-event); live=cancel_qty/(depth5_bid*mid+eps)*1e4 (5000ms windowed)",
        "ask_add_bps": "DIFFERENT FORMULA: research=add_qty/mid*1e4 (per-event); live=add_qty/(depth5_ask*mid+eps)*1e4 (5000ms windowed)",
        "cancel_pressure": "DIFFERENT FORMULA: research=(bc+ac)/d1 (per-event, BTC depth); live=(bc+ac)/(depth5_notional+eps) (5000ms windowed)",
        "tfi_500": "FIXED: research no longer prunes self.trades in-place; matches live non-destructive window filter",
        "liq_depletion": "FIXED: research no longer prunes self.trades in-place; matches live non-destructive window filter",
        "log_depth1": "PASS",
        "log_depth5": "PASS",
        "log_event_rate": "FIXED: research uses non-destructive 500ms window filter matching live",
        "depth_slope_bps": "Rounding (research: round(,6), live: no round). Diff ~5e-7. NOT MATERIAL",
        "vol_500": "RESEARCH COMPUTES (add_trailing_vol); LIVE HARDCODES 0.0",
    }
    failed_causes = {k: v for k, v in causes.items() if "PASS" not in v and "FIXED" not in v}
    if failed_causes:
        for feat in V5_FEATURES:
            if feat in failed_causes:
                print(f"  {feat:22s} → {failed_causes[feat]}")
    else:
        print("  (all features now match; no failed features)")

    return 0 if failed == 0 else 1


def test_out_of_order_exchange_timestamps():
    """Verify research and live produce identical tfi_500/liq_depletion/log_event_rate
    when exchange timestamps (E/T) are out of order relative to receive order (recv_ms).

    The critical scenario: events arrive in recv_ms order, but E/T values are NOT
    monotonically increasing. The research pipeline must NOT prune its trade buffer
    destructively, because a trade pruned by a high-E depth event may still be in
    the 500ms window for a subsequent lower-E trade event that arrives later in
    recv_ms order.
    """
    base_ts = 100_000_000
    snap_id = 1000
    events = [
        {"kind": "snapshot", "last_update_id": snap_id, "recv_ms": base_ts,
         "bids": [[100.0, 1.0], [99.0, 1.0]], "asks": [[101.0, 1.0], [102.0, 1.0]]},
        {"kind": "depth", "E": base_ts + 100, "U": snap_id + 1, "u": snap_id + 2,
         "recv_ms": base_ts + 10,
         "bids": [[100.0, 2.0]], "asks": [[101.0, 2.0]]},
        {"kind": "trade", "T": base_ts + 200, "a": 1, "p": 100.5, "q": 1.0,
         "m": True, "recv_ms": base_ts + 50},
        {"kind": "depth", "E": base_ts + 600, "U": snap_id + 3, "u": snap_id + 4,
         "recv_ms": base_ts + 60,
         "bids": [[100.0, 3.0]], "asks": [[101.0, 3.0]]},
        {"kind": "trade", "T": base_ts + 300, "a": 2, "p": 100.5, "q": 2.0,
         "m": False, "recv_ms": base_ts + 70},
    ]

    rdf = run_research_pipeline(events, "test")
    lrows = run_live_pipeline(events)

    assert len(rdf) == 4, f"Expected 4 research rows, got {len(rdf)}"
    assert len(lrows) == 4

    for i in range(4):
        for feat in ["tfi_500", "liq_depletion", "log_event_rate"]:
            r_val = safe_float(rdf.iloc[i].get(feat, 0.0))
            l_val = safe_float(getattr(lrows[i], feat, 0.0))
            assert abs(r_val - l_val) <= 1e-9, (
                f"Row {i} {feat}: research={r_val} live={l_val} "
                f"(exchange timestamps out of order)"
            )


def test_pruning_does_not_remove_future_window_trades():
    """Specifically verify that a trade within the 500ms window of a later (lower-T)
    event is NOT removed by an earlier (higher-E) event's pruning in the research
    pipeline.
    """
    base_ts = 100_000_000
    snap_id = 1000
    events = [
        {"kind": "snapshot", "last_update_id": snap_id, "recv_ms": base_ts,
         "bids": [[100.0, 1.0], [99.0, 1.0]], "asks": [[101.0, 1.0], [102.0, 1.0]]},
        {"kind": "depth", "E": base_ts + 100, "U": snap_id + 1, "u": snap_id + 2,
         "recv_ms": base_ts + 10,
         "bids": [[100.0, 2.0]], "asks": [[101.0, 2.0]]},
        {"kind": "trade", "T": base_ts + 200, "a": 1, "p": 100.5, "q": 1.0,
         "m": True, "recv_ms": base_ts + 50},
        {"kind": "depth", "E": base_ts + 800, "U": snap_id + 3, "u": snap_id + 4,
         "recv_ms": base_ts + 60,
         "bids": [[100.0, 3.0]], "asks": [[101.0, 3.0]]},
        {"kind": "trade", "T": base_ts + 500, "a": 2, "p": 100.5, "q": 2.0,
         "m": False, "recv_ms": base_ts + 70},
    ]

    rdf = run_research_pipeline(events, "test")
    lrows = run_live_pipeline(events)

    assert len(rdf) == 4, f"Expected 4 research rows, got {len(rdf)}"
    assert len(lrows) == 4

    r_trade_rate = int(rdf.iloc[3]["trade_rate"])
    l_log_er = safe_float(lrows[3].log_event_rate)
    expected_count = int(np.expm1(l_log_er))

    assert r_trade_rate == expected_count, (
        f"Research trade_rate={r_trade_rate} but live window count={expected_count} "
        f"at trade event T=500 (trade at T=200 should be retained)"
    )


if __name__ == "__main__":
    sys.exit(main())
