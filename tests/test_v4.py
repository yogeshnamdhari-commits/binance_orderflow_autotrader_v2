"""V4 tests: deterministic replay, maker fill sim, frozen-model signals,
verdict mapping, and regression against V3 (frozen model untouched)."""

import json

import numpy as np

from app import v4_fill, v4_replay, v4_signal, v4_validation, v4_verdict


def _snap(bid=100.0, bq=2.0, ask=100.5, aq=2.0):
    return {"kind": "snapshot", "last_update_id": 10, "ts_ms": 0, "recv_ms": 0,
            "bids": [[str(bid), str(bq)]], "asks": [[str(ask), str(aq)]]}


_U = [0]


def _depth(ts, bids=(), asks=()):
    _U[0] += 1001
    u = _U[0]
    return {"kind": "depth", "E": ts, "U": u, "u": u, "bids": list(bids),
            "asks": list(asks), "recv_ms": ts}


def _trade(ts, tid, price, qty, maker):
    return {"kind": "trade", "T": ts, "a": tid, "p": price, "q": qty,
            "m": maker, "recv_ms": ts}


def _mk_session_raw(path, lines):
    path.mkdir(parents=True, exist_ok=True)
    (path / "raw.jsonl").write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    rp = v4_replay.ReplayV4()
    for l in lines:
        rp.feed_line(json.dumps(l))
    assert rp.skips == 0
    (path / "derived_v4.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rp.rows) + "\n")
    return rp.rows


def test_v4_replay_is_v3_superset(tmp_path):
    from app.v3_replay import ReplayV3
    lines = [_snap(), _depth(1000, [[100.0, 3.0]], []),
             _trade(1200, 1, 100.0, 0.5, True),
             _depth(2000, [], [[100.5, 0.0], [101.0, 5.0]]),
             _trade(2500, 2, 100.5, 1.0, False)]
    p = tmp_path / "s"
    rows4 = _mk_session_raw(p, lines)
    r3 = ReplayV3()
    for l in lines:
        r3.feed_line(json.dumps(l))
    base_cols = [c for c in r3.rows[0] if not c.startswith("levels")
                 and c not in ("trade_price", "trade_qty", "trade_maker")]
    for a, b in zip(rows4, r3.rows):
        for c in base_cols:
            assert a[c] == b[c], c
    assert "levels_bid" in rows4[0] and len(rows4[0]["levels_bid"]) > 0
    assert rows4[1]["trade_price"] == 100.0 and rows4[1]["trade_qty"] == 0.5
    assert rows4[1]["trade_maker"] is True
    assert rows4[3]["trade_price"] == 100.5 and rows4[3]["trade_maker"] is False


def test_v4_fill_sweep_adverse(tmp_path):
    p = tmp_path / "s"
    rows = _mk_session_raw(p, [
        _snap(bid=90.0, bq=5.0, ask=110.0, aq=5.0),
        _depth(0, [], []),                                  # row0: book at 90
        _depth(1000, [[90.0, 0.0], [89.9, 3.0]], []),       # row1: best drops < 90
    ])
    ss = v4_fill.load_stream(p / "derived_v4.jsonl")
    assert ss.best(0, 0) == 90.0
    r = v4_fill.sim_maker_leg(ss, 0, +1, qty=1.0, max_wait_ms=5000)
    assert r["placed"] and r["reason"] == "swept"
    assert r["filled_ratio"] == 1.0
    assert abs(r["fill_price"] - 90.0) < 1e-12
    assert r["fill_time_ms"] == 1000


def test_v4_fill_trade_consumes_queue(tmp_path):
    p = tmp_path / "s"
    rows = _mk_session_raw(p, [
        _snap(bid=90.0, bq=5.0, ask=110.0, aq=5.0),
        _depth(0, [], []),
        _trade(500, 1, 90.0, 5.0, True),   # consumes the 5.0 queue ahead
        _trade(1000, 2, 90.0, 2.0, True),  # consumes our 2.0
    ])
    ss = v4_fill.load_stream(p / "derived_v4.jsonl")
    r = v4_fill.sim_maker_leg(ss, 0, +1, qty=2.0, max_wait_ms=5000)
    assert r["filled_ratio"] > 0.99 and r["reason"] == "trade"
    assert r["fill_time_ms"] == 1000


def test_v4_fill_deterministic(tmp_path):
    p = tmp_path / "s"
    lines = [_snap(bid=90.0, bq=5.0, ask=110.0, aq=5.0),
             _depth(0, [], []),
             _depth(500, [[90.0, 3.0]], []), _trade(800, 1, 90.0, 7.0, True)]
    _mk_session_raw(p, lines)
    ss = v4_fill.load_stream(p / "derived_v4.jsonl")
    r1 = v4_fill.sim_maker_leg(ss, 0, +1, 2.0)
    r2 = v4_fill.sim_maker_leg(ss, 0, +1, 2.0)
    assert r1 == r2


def test_v4_signal_no_fill_penalizes(tmp_path):
    from app.v3_model import calibrate
    p = tmp_path / "s"
    n = 4000
    lines = [_snap(bid=90.0, bq=8.0, ask=90.1, aq=8.0)]
    for k in range(n):
        bid = 90.0 + 0.005 * k
        lines.append(_depth(1000 + k * 10, [[bid, 8.0], [bid - 0.01, 3.0]],
                            [[bid * 1.001, 8.0]]))
    rows4 = _mk_session_raw(p, lines)
    # tiny frozen exp: build features+small model to feed session_signals
    import pandas as pd
    dv = p / "derived_v4.jsonl"
    rows = [json.loads(l) for l in dv.open() if l.strip()]
    df = pd.DataFrame(rows)
    df["session"] = "s"
    cols = ["ts_ms", "recv_ms", "session", "kind", "seq", "best_bid",
            "best_ask", "mid", "microb_price", "spread_bps", "mpd_bps",
            "qi_l1", "di_l5", "di_l10", "depth_slope_bps", "ofi_l1",
            "ofi_norm_l1", "bid_add_bps", "bid_cancel_bps", "ask_add_bps",
            "ask_cancel_bps", "cancel_pressure", "log_depth1", "log_depth5",
            "log_event_rate", "tfi_500", "signed_vol_500", "trade_rate",
            "liq_depletion", "regime"]
    df[cols].to_parquet(tmp_path / "f.parquet", index=False)
    calibrate(tmp_path / "f.parquet", tmp_path)
    model = json.load(open(tmp_path / "v3_model.json"))
    oos = np.ones(len(rows), dtype=bool)
    samples, _ = v4_signal.session_signals("s", rows, model, oos)
    assert any(x["posted"] for x in samples)
    # no_fill samples carry a net penalty
    nf = [x for x in samples if x["state"] == "NO_FILL"]
    if nf:
        assert all(x["net_bps"] < 0 for x in nf)


def test_v4_validation_and_verdict(tmp_path):
    ss = {"conclusion": "valid", "samples": 6000, "posted_signals": 4000,
          "entries_filled": 3000, "fill_probability": 0.75,
          "full_fill_probability": 0.9, "partial_fill_probability": 0.1,
          "median_time_to_fill_ms": 120.0, "p95_time_to_fill_ms": 900.0,
          "net_expectancy_bps": 1.20, "profit_factor": 1.4, "sharpe": 1.1,
          "max_drawdown_bps": -12.0,
          "adverse_selection_mean_bps": 0.05,
          "adverse_selection_median_bps": 0.04,
          "adverse_selection_p95_bps": 0.3,
          "fill_conditional_drag_bps": 0.04, "unconditional_gross_bps": 1.3,
          "oos_periods": 5, "largest_session_net_share": 0.25,
          "per_session": {"a": {"signals": 1200, "net_mean_bps": 1.0},
                          "b": {"signals": 1400, "net_mean_bps": 1.3},
                          "c": {"signals": 1100, "net_mean_bps": 1.1},
                          "d": {"signals": 1200, "net_mean_bps": 0.9},
                          "e": {"signals": 1100, "net_mean_bps": 1.2}}}
    assert v4_verdict.decide(ss)["verdict"] == "PASS"

    ss2 = dict(ss, net_expectancy_bps=-0.4)
    assert v4_verdict.decide(ss2)["verdict"] == "FAIL"

    ss3 = dict(ss, posted_signals=80)
    v = v4_verdict.decide(ss3)
    assert v["verdict"] in ("CONDITIONAL_PASS", "INSUFFICIENT_DATA")

    ss4 = dict(ss, largest_session_net_share=0.85)
    assert v4_verdict.decide(ss4)["verdict"] == "FAIL"

    ss5 = dict(ss, fill_conditional_drag_bps=1.5, unconditional_gross_bps=1.3)
    assert v4_verdict.decide(ss5)["verdict"] == "FAIL"


def _mini():
    return {"conclusion": "valid", "samples": 10, "posted_signals": 8,
            "entries_filled": 4, "net_expectancy_bps": 0.9, "oos_periods": 1,
            "largest_session_net_share": 1.0, "per_session": {}}


def test_v4_insufficient_data():
    m = _mini()
    assert v4_verdict.decide(m)["verdict"] == "INSUFFICIENT_DATA"