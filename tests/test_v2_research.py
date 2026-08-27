import json

import numpy as np
import pandas as pd

from app.l2_replay import Replay
from app import v2_features, v2_labels, v2_model, v2_cost_gate, v2_validation


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


def _base_recs():
    return [
        _depth(1000, [[100.0, 3.0]], []),
        _trade(1100, 1, 1.0, False),
        _trade(1200, 2, 0.5, True),
        _trade(1500, 3, 2.0, False),
        _depth(2000, [], [[100.5, 4.0]]),
        _depth(3000, [], [[100.5, 0.0], [101.0, 5.0]]),
    ]


def test_features_tfi_windows_and_intensity(tmp_path):
    sess = tmp_path / "s"
    _make_session(sess, _base_recs())
    feat = v2_features.build_session_features(tmp_path / "f.parquet", [sess])
    df = pd.read_parquet(feat)
    row = df.set_index("ts_ms")

    assert row.loc[1500, "tfi_250"] == 1.0            # only the 1500 BUY inside [1250,1500]
    assert row.loc[1500, "buy_vol_250"] == 2.0
    assert row.loc[1500, "sell_vol_250"] == 0.0
    assert abs(row.loc[1500, "tfi_1000"] - (2.5 / 3.5)) < 1e-6
    assert row.loc[1500, "trade_rate"] == 3.0          # trade rows at 1100/1200/1500
    assert row.loc[1500, "book_rate"] == 1.0           # depth at 1000

    assert row.loc[2000, "tfi_500"] == 1.0             # window (1500,2000] -> BUY 2.0
    assert row.loc[2000, "buy_vol_500"] == 2.0
    assert abs(row.loc[2000, "nofi_1"] - (-2.0 / 7.0)) < 1e-6


def test_labels_are_strictly_future_and_winnow_tail(tmp_path):
    sess = tmp_path / "s"
    _make_session(sess, _base_recs())
    feat = v2_features.build_session_features(tmp_path / "f.parquet", [sess])
    lab = v2_labels.add_labels(pd.read_parquet(feat))
    row = lab.set_index("ts_ms")
    # mid @2000 = 100.25 ; first event >= 2500 is the depth at 3000 -> mid 100.5
    expected = (100.5 - 100.25) / 100.25 * 1e4
    assert abs(row.loc[2000, "r_500"] - expected) < 1e-4
    assert not np.isnan(row.loc[2000, "r_1000"])
    # tail events (no strictly-future reference at 1000ms) get NaN
    assert bool(np.isnan(row.loc[3000, "r_1000"]))
    # r_500 is exactly the return implied by future_mid_500 (label consistency)
    chk = (lab.dropna(subset=["r_500"]).future_mid_500 - lab.dropna(subset=["r_500"]).mid) \
        / lab.dropna(subset=["r_500"]).mid * 1e4
    assert np.allclose(chk.to_numpy(), lab.dropna(subset=["r_500"]).r_500.to_numpy(), atol=1e-9)


def _engineered_frame(n, spacing_ms, y, seed):
    """Builds a features frame whose r_500 label equals y (bps) by construction
    through the mid series (r_500[i] = (mid[i+2]-mid[i])/mid[i]*1e4)."""
    rng = np.random.default_rng(seed)
    ts = np.arange(1, n + 1) * spacing_ms
    x1 = rng.normal(size=n)
    x2 = rng.normal(size=n)
    id_ = np.arange(n)
    mid = np.full(n, 100.0)
    for i in range(n - 3, -1, -1):
        mid[i] = mid[i + 2] / (1.0 + y[i] / 1e4)
    return pd.DataFrame({
        "ts_ms": ts, "session": "test", "kind": "depth", "mid": mid,
        "nofi_1": x1, "nofi_5": 0.0, "nofi_10": 0.0, "tfi_500": x2,
        "qi1": 0.0, "qi5": 0.0, "qi10": 0.0, "mpd_bps": 0.0,
        "spread_bps": 0.01, "log_depth10": 4.0, "log_event_rate": 1.0,
        "microb_price": mid, "recv_ms": ts, "seq": id_.tolist(),
    })


def test_model_calibrate_recovers_signs_and_freezes(tmp_path):
    rng = np.random.default_rng(7)
    n = 4000
    x1 = rng.normal(size=n)
    x2 = rng.normal(size=n)
    y = 3.0 * x1 - 2.0 * x2 + rng.normal(scale=0.1, size=n)
    df = _engineered_frame(n, 250, y, 7)
    path = tmp_path / "f.parquet"
    df.to_parquet(path)
    m, c = v2_model.calibrate(path, tmp_path, horizon_ms=(250, 500, 1000))

    c500 = np.array(m["500"]["coef"])
    f1 = v2_model.MODEL_FEATURES.index("nofi_1")
    f2 = v2_model.MODEL_FEATURES.index("tfi_500")
    assert c500[f1] > 0.5 and c500[f2] < -0.5
    assert m["500"]["r2_train"] > 0.9
    # freeze determinism: rerun identical -> identical coefficients
    m2, _ = v2_model.calibrate(path, tmp_path / "b", horizon_ms=(250, 500, 1000))
    assert [round(x, 9) for x in m["500"]["coef"]] == [round(x, 9) for x in m2["500"]["coef"]]


def test_cost_gate_uses_measured_costs():
    cal = {
        "effective_taker_roundtrip": {"1000": {"p90_bps": 4.0158}},
        "maker_fee_rt_bps": 2.0,
        "oos_fill": {
            "a@5s": {"p_fill_same_tick": 0.7123, "gross_unconditional_bps": 1.866,
                     "e_fill_return_bps": 1.328},
            "b@5s": {"p_fill_same_tick": 0.7065, "gross_unconditional_bps": 1.743,
                     "e_fill_return_bps": 1.223},
        },
    }
    tak = v2_cost_gate.taker_cost_bps(cal, 1000)
    assert abs(tak - (4.0158 + 0.10 + 0.05)) < 1e-6
    comp = v2_cost_gate.maker_components(cal)
    assert abs(comp["adverse_selection_bps"] - (0.538 + 0.520) / 2) < 1e-6
    e = v2_cost_gate.decide(3.0, cal, 1000, "taker")
    assert e["state"] == "NO_TRADE"          # 3.0 < 4.1658
    e2 = v2_cost_gate.decide(-5.0, cal, 1000, "taker")
    assert e2["state"] == "SHORT"            # -(-5) = +5 > cost -> short net 0.83
    e3 = v2_cost_gate.decide(5.0, cal, 1000, "taker")
    assert e3["state"] == "LONG"


def test_validation_reports_oos_verdict(tmp_path):
    rng = np.random.default_rng(11)
    n = 6000
    x1 = rng.normal(size=n)
    x2 = rng.normal(size=n)
    y = 2.0 * x1 + 0.5 * x2 + rng.normal(scale=0.2, size=n)
    df = _engineered_frame(n, 120, y, 11)
    fp = tmp_path / "f.parquet"
    df.to_parquet(fp)
    v2_model.calibrate(fp, tmp_path, horizon_ms=(250, 500, 1000))
    cal = tmp_path / "cal.json"
    cal.write_text(json.dumps({
        "effective_taker_roundtrip": {"1000": {"p90_bps": 1.0}},
        "maker_fee_rt_bps": 2.0, "oos_fill": {}, "spread": {"p90_bps": 0.5},
        "slippage_by_notional": {"1000": {"buy_p90_bps": 0.05}}}))
    r = v2_validation.validate(tmp_path / "v2_model.json", cal, fp, tmp_path,
                               horizon_ms=500)
    assert r["blocks"]["oos"]["long"]["n"] > 100
    assert r["verdict"] in ("PASS", "STOP")
    assert "cost_bps" in r and r["cost_bps"] > 0