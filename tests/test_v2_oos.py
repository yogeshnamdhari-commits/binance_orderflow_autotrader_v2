"""V2 OOS freeze / integrity / robustness / verdict / economic report tests."""

import json

import numpy as np
import pandas as pd

from app import (v2_labels, v2_model, v2_robustness, v2_verdict,
                 v2_manifest, v2_data_integrity, v2_economic_report)
from app.l2_replay import Replay


# ---------------------------------------------------------------- manifest
def test_manifest_freezes_and_verifies(tmp_path):
    m, p = v2_manifest.freeze_only(tmp_path)
    assert p.exists()
    assert "freeze_id" in m and "body" in m
    assert "app/v2_model.py" in m["body"]["modules"]
    v = v2_manifest.verify_free(m)
    assert v["modules_match"] is True
    assert v["artifacts_match"] is True
    assert v["freeze_id_match"] is True


# ------------------------------------------------------------ data integrity
def _snapshot():
    return {"kind": "snapshot", "last_update_id": 10, "ts_ms": 0, "recv_ms": 0,
            "bids": [["100.0", "2"], ["99.5", "1"]],
            "asks": [["100.5", "2"], ["101.0", "1"]]}


def _depth(ts, bids, asks, recv=None):
    return {"kind": "depth", "E": ts, "U": ts, "u": ts,
            "bids": bids, "asks": asks, "recv_ms": recv if recv is not None else ts}


def _trade(ts, tid, q, m, recv=None):
    return {"kind": "trade", "T": ts, "a": tid, "p": 100.5, "q": q,
            "m": m, "recv_ms": recv if recv is not None else ts}


def _make_session(path, recs):
    path.mkdir(parents=True)
    lines = [_snapshot()] + recs
    (path / "raw.jsonl").write_text("\n".join(json.dumps(r) for r in lines) + "\n")
    replay = Replay()
    for line in lines:
        replay.feed_line(json.dumps(line))
    (path / "derived.jsonl").write_text(
        "\n".join(json.dumps(r) for r in replay.rows) + "\n")


def test_integrity_sessions_verified(tmp_path):
    s = tmp_path / "s"
    _make_session(s, [
        _depth(1000, [[100.0, 3.0]], []),
        _trade(1100, 1, 1.0, False),
        _trade(1200, 2, 0.5, True),
        _trade(1500, 3, 2.0, False),
        _depth(2000, [], [[100.5, 4.0]]),
        _depth(3000, [], [[100.5, 0.0], [101.0, 5.0]]),
    ])
    out = v2_data_integrity.collect_integrity([s])
    assert out["all_replay_mismatches_zero"] is True
    assert out["all_snapshot_present"] is True
    assert out["all_verified"] is True
    sess = out["sessions"][0]
    assert sess["book_gap_events"] == 0  # replay skipped nothing


def test_integrity_detects_gap(tmp_path):
    s = tmp_path / "s"
    _make_session(s, [
        _depth(1000, [[100.0, 3.0]] * 10, []),
        {"kind": "depth", "E": 2000, "U": 9000, "u": 9000,
         "bids": [], "asks": [[100.5, 4.0]], "recv_ms": 2000},
    ])
    out = v2_data_integrity.collect_integrity([s])
    assert out["sessions"][0]["book_gap_events"] == 1   # replay gap -> re-sync skip
    assert out["sessions"][0]["max_update_gap"] == 7999  # 9000-1000-1


# ---------------------------------------------------------------- robustness
def _engineered_frame(n, spacing_ms, x1, y, seed):
    rng = np.random.default_rng(seed)
    ts = np.arange(1, n + 1) * spacing_ms
    id_ = np.arange(n)
    mid = np.full(n, 100.0)
    for i in range(n - 3, -1, -1):
        mid[i] = mid[i + 2] / (1.0 + y[i] / 1e4)
    return pd.DataFrame({
        "ts_ms": ts, "session": "test", "kind": "depth", "mid": mid,
        "nofi_1": x1, "nofi_5": 0.0, "nofi_10": 0.0, "tfi_500": 0.0,
        "qi1": 0.0, "qi5": 0.0, "qi10": 0.0, "mpd_bps": 0.0,
        "spread_bps": 0.01, "log_depth10": 4.0, "log_event_rate": 1.0,
        "microb_price": mid, "recv_ms": ts, "seq": id_.tolist(),
    })


def _alt_signal(n, horizon):
    x1 = np.array([1.0, -1.0] * (n // 2 + 1))[:n]
    y = 3.0 * x1
    return x1, y, np.full(n, 100.0)


def test_robustness_cells_and_partition(tmp_path):
    rng = np.random.default_rng(5)
    n_tr, n_oo = 3000, 900
    x1, y, mid = _alt_signal(n_tr + n_oo, 1)
    train = {"pred": y[:n_tr], "label": y[:n_tr] / 1e1,
             "ts": np.arange(n_tr), "liquidity": rng.uniform(2, 4, n_tr),
             "spread_bps": rng.uniform(0.005, 0.05, n_tr),
             "r_250": np.full(n_tr, 0.0)}
    oos = {"pred": y[n_tr:], "label": y[n_tr:] / 1e1,
           "ts": np.arange(n_oo), "liquidity": rng.uniform(2, 4, n_oo),
           "spread_bps": rng.uniform(0.005, 0.05, n_oo),
           "r_250": np.full(n_oo, 0.0)}
    res = v2_robustness.evaluate(oos, train, {"taker_bps": 0.1})
    names = {c["name"] for c in res["cells"]}
    assert any(n.startswith("time_block_") for n in names)
    assert any(n.startswith("liquidity_tercile") for n in names)
    assert any(n.startswith("spread_tercile") for n in names)
    assert any(n.startswith("vol_tercile") for n in names)
    assert res["viable_cells"] > 0
    assert 0.0 <= res["positive_fraction"] <= 1.0
    assert all(c["long_n"] + c["short_n"] == c["n"] for c in res["cells"])


# ------------------------------------------------------------------- verdict
def test_verdict_conditional_when_small():
    oos = {"oos_periods": 1, "long": {"n": 10}, "short": {"n": 10},
           "net_expectancy_taker_bps": 1.0, "net_expectancy_maker_bps": 1.0}
    r = v2_verdict.decide(oos, {"cells": []})
    assert r["verdict"] == "CONDITIONAL PASS"


def test_verdict_pass_and_fail():
    def robust_pos():
        return {"cells": [{"name": f"c{i}", "n": 50, "net_mean_bps": 0.1}
                          for i in range(6)]}
    enough = {"oos_periods": 4, "long": {"n": 300}, "short": {"n": 300},
              "net_expectancy_taker_bps": 1.2,
              "net_expectancy_maker_bps": 0.9}
    assert v2_verdict.decide(enough, robust_pos())["verdict"] == "PASS"

    bad = dict(enough)
    bad["net_expectancy_taker_bps"] = -1.0
    assert v2_verdict.decide(bad, robust_pos())["verdict"] == "FAIL"
    luck = {"cells": [{"name": f"c{i}", "n": 50,
                       "net_mean_bps": 0.1 if i == 0 else -0.2}
                      for i in range(6)]}
    assert v2_verdict.decide(dict(enough), luck)["verdict"] == "FAIL"


# ---------------------------------------------------------- economic report
def _build_dataset(tmp_path, horizon=500):
    rng = np.random.default_rng(11)
    n = 8000
    x1, y, mid = _alt_signal(n, 0)
    df = _engineered_frame(n, 120, x1, y, 11)
    fp = tmp_path / "f.parquet"
    df.to_parquet(fp)
    labs = v2_labels.add_labels(pd.read_parquet(fp))
    labs.to_parquet(fp)
    v2_model.calibrate(fp, tmp_path, horizon_ms=(250, 500, 1000))
    cal = tmp_path / "cal.json"
    cal.write_text(json.dumps({
        "effective_taker_roundtrip": {"1000": {"p90_bps": 0.5}},
        "maker_fee_rt_bps": 0.1, "oos_fill": {}, "spread": {"p90_bps": 0.01}}))
    return fp, cal


def test_economic_report_end_to_end(tmp_path):
    fp, cal = _build_dataset(tmp_path)
    model_d = v2_model.load_model(tmp_path / "v2_model.json")
    df = v2_labels.add_labels(pd.read_parquet(fp))
    import types
    a = types.SimpleNamespace(
        rundir=tmp_path, features=fp, labels=None, model=tmp_path / "v2_model.json",
        cost_cal=cal, horizon_ms=500, notional_usd=1000.0,
        train_n=int(model_d["splits"]["train"]["rows"]), oos_periods=4,
        out=tmp_path / "V2_ECONOMIC_REPORT.json")
    report = v2_economic_report.build_report(a, df, model_d)
    p = v2_economic_report.write_report(a.out, report)
    assert p.exists()
    assert report["verdict"]["verdict"] in ("PASS", "CONDITIONAL PASS", "FAIL")
    assert report["taker"]["long"]["n"] > 0
    assert report["taker"]["short"]["n"] > 0
    assert report["robustness"]["cells"]
    assert report["distributions"]["spread_n"] == len(df) - a.train_n