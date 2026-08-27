"""V5 tests — frozen lineage: causal trailing vol, strict-future labels,
train-only ridge freeze, measured gate decision states, verdict mapping."""

import numpy as np

from app import v2_verdict, v3_labels, v5_cost, v5_features, v5_manifest, v5_model


def _feature_frame(n=1200):
    import pandas as pd
    ts = np.arange(n, dtype=np.int64)
    mid = 100.0 + 0.001 * np.arange(n)
    return pd.DataFrame({
        "ts_ms": ts, "recv_ms": ts, "session": "s", "kind": "depth", "seq": "1",
        "best_bid": mid - 0.01, "best_ask": mid + 0.01, "mid": mid,
        "microb_price": mid, "spread_bps": 1.0, "mpd_bps": 0.0,
        "qi_l1": 0.0, "di_l5": 0.0, "di_l10": 0.0, "depth_slope_bps": 0.0,
        "ofi_l1": 0.0, "ofi_norm_l1": 0.0, "bid_add_bps": 0.0,
        "bid_cancel_bps": 0.0, "ask_add_bps": 0.0, "ask_cancel_bps": 0.0,
        "cancel_pressure": 0.0, "log_depth1": 1.0, "log_depth5": 2.0,
        "log_event_rate": 1.0, "tfi_500": 0.0, "signed_vol_500": 0.0,
        "trade_rate": 1, "liq_depletion": 0.0, "regime": "normal",
        "vol_500": 1.0, "vol_2000": 1.0})


def test_trailing_vol_is_causal():
    df = _feature_frame(900)
    df.loc[300:, "mid"] = df.loc[300:, "mid"] + 0.5   # jump after row 300
    out = v5_features.add_trailing_vol(df)
    assert {"vol_500", "vol_2000"} <= set(out.columns)
    early = out.loc[100:240, "vol_500"].to_numpy(float)   # window before jump
    late = out.loc[305:335, "vol_500"].to_numpy(float)     # window covering jump
    assert np.nanmax(early) < np.nanmin(late)


def test_trailing_vol_uses_no_future():
    df = _feature_frame(400)
    out = v5_features.add_trailing_vol(df)
    df2 = _feature_frame(400)
    df2.loc[20, "mid"] = 500.0     # change only row 20
    out2 = v5_features.add_trailing_vol(df2)
    # rows strictly before the perturbed window must be unchanged
    assert np.allclose(out.loc[:15, "vol_500"].to_numpy(float),
                       out2.loc[:15, "vol_500"].to_numpy(float),
                       equal_nan=True)


def test_labels_v5_reuse_strict_future():
    df = v3_labels.add_labels(_feature_frame(800), (250, 500, 1000))
    ts = df["ts_ms"].to_numpy(dtype=np.int64)
    mid = df["mid"].to_numpy(dtype=float)
    ptr = np.searchsorted(ts, ts + 500, side="left")
    finite = np.isfinite(df["r_500"].to_numpy())
    assert (ptr[finite] > np.arange(len(df))[finite]).all()  # strictly future
    expect = (mid[ptr[finite]] - mid[finite]) / mid[finite] * 1e4
    assert np.allclose(df.loc[finite, "r_500"].to_numpy(float), expect)


def test_model_freeze_deterministic(tmp_path):
    df = v3_labels.add_labels(_feature_frame(1500), (250, 500, 1000))
    df.to_parquet(tmp_path / "f.parquet", index=False)
    m1, _ = v5_model.calibrate(tmp_path / "f.parquet", tmp_path)
    m2 = v5_model.load_model(tmp_path / "v5_model.json")
    for h in ("250", "500", "1000"):
        assert m1[h]["coef"] == m2[h]["coef"] and m1[h]["n_train"] > 200
    assert v5_model.predict(m1, df.head(50), 500).shape == (50,)


def test_cost_gate_states():
    gate = 4.6658
    assert v5_cost.decide(5.0, gate)["state"] == "LONG"
    assert v5_cost.decide(-5.0, gate)["state"] == "SHORT"
    assert v5_cost.decide(1.0, gate)["state"] == "NO_TRADE"
    s = v5_cost.sensitivity_gates(gate)
    assert s["gate"] == gate and s["gate_minus_1"] == gate - 1.0
    assert s["gate_plus_1"] == gate + 1.0


def test_measured_gate_positive_from_cal():
    assert v5_cost.measured_gate() > 4.0
    assert v5_cost.total_cost_bps() > 0.0


def test_manifest_build_verify(tmp_path):
    m = v5_manifest.build_manifest(tmp_path)
    v = v5_manifest.verify(tmp_path)
    assert v["verified"] is True
    assert v["frozen_id"] == m["freeze_id"]


def test_verdict_no_pass_with_2_oos_periods():
    v = v2_verdict.decide(
        {"oos_periods": 2, "long": {"n": 500}, "short": {"n": 500},
         "net_expectancy_taker_bps": 0.1, "net_expectancy_maker_bps": 0.1},
        {"cells": [{"n": 100, "net_mean_bps": 0.1}] * 6})
    assert v["verdict"] == "FAIL"   # periods < 3 blocks even positive economics