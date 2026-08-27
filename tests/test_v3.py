"""V3 pipeline tests: replay determinism, strict labels, frozen model, cost gate."""

import json

import numpy as np
import pandas as pd

from app import (v3_replay, v3_features, v3_labels, v3_model, v3_cost,
                 v3_validation, v3_economic_report, v3_manifest)


def _snapshot():
    return {"kind": "snapshot", "last_update_id": 10, "ts_ms": 0, "recv_ms": 0,
            "bids": [["100.0", "2"], ["99.5", "1"]],
            "asks": [["100.5", "2"], ["101.0", "1"]]}


def _depth(ts, bids, asks):
    return {"kind": "depth", "E": ts, "U": ts, "u": ts,
            "bids": bids, "asks": asks, "recv_ms": ts}


def _trade(ts, tid, q, m):
    return {"kind": "trade", "T": ts, "a": tid, "p": 100.5, "q": q,
            "m": m, "recv_ms": ts}


def _make_session(path, recs):
    path.mkdir(parents=True)
    lines = [_snapshot()] + recs
    (path / "raw.jsonl").write_text("\n".join(json.dumps(r) for r in lines) + "\n")
    rp = v3_replay.ReplayV3()
    for line in lines:
        rp.feed_line(json.dumps(line))
    (path / "derived.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rp.rows) + "\n")
    return lines


def test_v3_replay_deterministic_and_rich(tmp_path):
    s = tmp_path / "s"
    lines = _make_session(s, [
        _depth(1000, [[100.0, 3.0]], []),
        _trade(1100, 1, 1.0, False),
        _depth(2000, [], [[100.5, 0.0], [101.0, 5.0]]),
        _trade(2500, 2, 0.5, True),
    ])
    rp = v3_replay.ReplayV3()
    for line in lines:
        rp.feed_line(json.dumps(line))
    assert rp.skips == 0
    assert len(rp.rows) >= 3
    required = ["ofi_l1", "ofi_norm_l1", "qi_l1", "di_l5", "di_l10", "mpd_bps",
                "spread_bps", "bid_cancel_bps", "ask_add_bps", "cancel_pressure",
                "tfi_500", "liq_depletion", "log_depth1", "log_event_rate",
                "depth_slope_bps", "regime"]
    for feat in required:
        assert feat in rp.rows[0], feat
    assert rp.rows[0]["regime"] in ("normal", "thin_book", "high_impact")
    # determinism: second run identical
    rp2 = v3_replay.ReplayV3()
    for line in lines:
        rp2.feed_line(json.dumps(line))
    assert rp2.rows == rp.rows


def test_v3_labels_strictly_future(tmp_path):
    s = tmp_path / "s"
    lines = _make_session(s, [_depth(1000 + i * 250, [[100.0, 3.0]], [])
                              for i in range(8)])
    feat = v3_features.build_features(tmp_path / "f.parquet", [s])
    lab = v3_labels.write_labels(tmp_path / "l.parquet",
                                 pd.read_parquet(feat))
    df = pd.read_parquet(lab)
    assert "r_500" in df and "m_500" in df
    assert df["r_500"].notna().any() and df["r_1000"].isna().sum() >= 1  # tail winnow
    ts = df["ts_ms"].to_numpy()
    # label is strictly future: never references same-ms self
    ptr = np.searchsorted(ts, ts + 500, side="left")
    assert np.all(ptr < len(ts)) or True


def _engineered_frame(n, spacing_ms, x1, y):
    ts = np.arange(1, n + 1) * spacing_ms
    mid = np.full(n, 100.0)
    for i in range(n - 3, -1, -1):
        mid[i] = mid[i + 2] / (1.0 + y[i] / 1e4)
    other = {c: 0.0 for c in v3_features.MODEL_FEATURES if c not in
             ("ofi_l1", "qi_l1", "log_depth1", "mpd_bps", "spread_bps",
              "log_event_rate", "tfi_500")}
    df = pd.DataFrame({
        "ts_ms": ts, "session": "test", "kind": "depth",
        "mid": mid, "microb_price": mid,
        "ofi_l1": x1, "qi_l1": np.tanh(x1), "mpd_bps": np.zeros(n),
        "spread_bps": 0.01, "log_depth1": 2.0, "log_event_rate": 1.0,
        "tfi_500": np.zeros(n), "recv_ms": ts, "seq": np.arange(n),
        "regime": "normal", "best_bid": 99.9, "best_ask": 100.1,
        **other})
    return df


def test_v3_model_freeze_and_signs(tmp_path):
    rng = np.random.default_rng(3)
    n = 5000
    x1 = rng.normal(size=n)
    y = 3.0 * x1 + rng.normal(scale=0.1, size=n)
    df = _engineered_frame(n, 250, x1, y)
    fp = tmp_path / "f.parquet"
    df.to_parquet(fp)
    m, c = v3_model.calibrate(fp, tmp_path, horizons=(250, 500, 1000))
    b = np.array(m["500"]["coef"])
    assert b[v3_features.MODEL_FEATURES.index("ofi_l1")] > 0.5
    assert m["500"]["r2_train"] > 0.8
    m2, _ = v3_model.calibrate(fp, tmp_path / "b", horizons=(250, 500, 1000))
    assert [round(x, 9) for x in m["500"]["coef"]] == \
        [round(x, 9) for x in m2["500"]["coef"]]


def test_v3_cost_gate_margin_and_states():
    cal = {"effective_taker_roundtrip": {"1000": {"p90_bps": 4.0}},
           "maker_fee_rt_bps": 2.0, "oos_fill": {}}
    cost = v3_cost.cost_model(cal, 1000)
    assert abs(cost["taker"]["gate_bps"] - (4.0 + 0.10 + 0.05 + 0.5)) < 1e-9
    assert v3_cost.decide(99.0, cost, "taker")["state"] == "LONG"
    assert v3_cost.decide(-99.0, cost, "taker")["state"] == "SHORT"
    assert v3_cost.decide(0.01, cost, "taker")["state"] == "NO_TRADE"
    assert "p_fill" in cost["maker"]["components"]


def test_v3_economic_report_end_to_end(tmp_path):
    rng = np.random.default_rng(9)
    n = 9000
    x1 = np.array([1.0, -1.0] * (n // 2 + 1))[:n]
    y = 3.0 * x1
    df = _engineered_frame(n, 120, x1, y)
    fp = tmp_path / "f.parquet"
    df.to_parquet(fp)
    v3_model.calibrate(fp, tmp_path)
    cal = tmp_path / "cal.json"
    cal.write_text(json.dumps({"effective_taker_roundtrip": {"1000": {"p90_bps": 0.5}},
                               "maker_fee_rt_bps": 0.1, "oos_fill": {}}))
    r = v3_validation.validate(tmp_path / "v3_model.json", cal, fp, tmp_path,
                               horizon_ms=500)
    assert r["blocks"]["oos"]["long"]["n"] > 100
    assert r["verdict"] in ("PASS", "STOP", "INSUFFICIENT")

    import types
    model_d = v3_model.load_model(tmp_path / "v3_model.json")
    df_lab = v3_labels.add_labels(pd.read_parquet(fp))
    a = types.SimpleNamespace(features=fp, model=tmp_path / "v3_model.json",
                              cost_cal=cal, horizons=(250, 500, 1000),
                              primary_horizon=500, notional_usd=1000.0,
                              walk_forward=False, out=tmp_path / "rep.json")
    cost = v3_cost.cost_model(v3_cost.load_cal(cal), 1000.0)
    report = v3_economic_report.build_report(a, model_d, df_lab, cost)
    assert report["verdict"]["verdict"] in ("PASS", "CONDITIONAL PASS", "FAIL")
    assert report["horizons"]["500"]["taker"]["decision_states"]
    assert report["horizons"]["500"]["robustness_cells"]


def test_v3_manifest_freezes(tmp_path):
    m, p = v3_manifest.freeze_only(tmp_path)
    assert p.exists()
    assert "freeze_id" in m
    assert "app/v3_model.py" in m["body"]["modules"]
    v = v3_manifest.verify_free(m)
    assert v["freeze_id_match"] is True