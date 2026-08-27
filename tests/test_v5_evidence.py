"""V5.1 evidence tests — frozen-model scoring harness, decision tree, manifest.
No live collection in tests; sessions are synthetic/offline."""

import json
import shutil

import numpy as np

from app import v5_evidence as ev
from app.v5_model import load_model, predict


def _synthetic_derived(path, n=3000, drift_bps=0.05, tear_bps=1000.0):
    """Synthetic derived_v5.jsonl with a tiny controllable forward-move content."""
    import pandas as pd
    path.mkdir(parents=True, exist_ok=True)
    ts = np.arange(n, dtype=np.int64)
    rng = np.random.default_rng(1234)
    mid = 100.0 + drift_bps / 1e4 * ts
    df = pd.DataFrame({
        "ts_ms": ts, "recv_ms": ts, "kind": "depth", "seq": "1",
        "session": path.name,
        "best_bid": mid - 0.01, "best_ask": mid + 0.01, "mid": mid,
        "microb_price": mid, "spread_bps": 1.0 + 0.1 * rng.standard_normal(n),
        "mpd_bps": 0.05 * rng.standard_normal(n),
        "qi_l1": 0.05 * rng.standard_normal(n), "di_l5": 0.05 * rng.standard_normal(n),
        "di_l10": 0.05 * rng.standard_normal(n), "depth_slope_bps": 0.1 * rng.standard_normal(n),
        "ofi_l1": 0.05 * rng.standard_normal(n), "ofi_norm_l1": 0.05 * rng.standard_normal(n),
        "bid_add_bps": 0.05 * rng.standard_normal(n),
        "bid_cancel_bps": 0.05 * rng.standard_normal(n),
        "ask_add_bps": 0.05 * rng.standard_normal(n),
        "ask_cancel_bps": 0.05 * rng.standard_normal(n),
        "cancel_pressure": 0.05 * rng.standard_normal(n), "log_depth1": 1.0 + 0.1 * rng.standard_normal(n),
        "log_depth5": 2.0 + 0.1 * rng.standard_normal(n),
        "log_event_rate": 1.0, "tfi_500": 0.05 * rng.standard_normal(n),
        "signed_vol_500": 0.05 * rng.standard_normal(n), "trade_rate": 1,
        "liq_depletion": 0.05 * rng.standard_normal(n), "regime": "normal"})
    df = ev.add_trailing_vol(df)
    with open(path / "derived_v5.jsonl", "w") as f:
        for _, r in df.iterrows():
            f.write(json.dumps({k: v for k, v in r.items()
                                if k not in ("vol_500", "vol_2000")}) + "\n")


def test_harness_reproduces_frozen_gross(tmp_path):
    """On a labeled series with a planted small drift, gross tracks the drift
    sign and the gate never fires for tiny predictions (harness validation)."""
    _synthetic_derived(tmp_path / "s1")
    _synthetic_derived(tmp_path / "s2")
    ev.build_evidence_features([tmp_path / "s1", tmp_path / "s2"],
                               tmp_path / "feat.parquet")
    m = load_model(ev.MODEL_PATH)
    gate = 4.6658
    met = ev.session_metrics(tmp_path / "feat.parquet", m, gate)
    assert len(met) == 2
    for x in met:
        assert x["eligible_signals"] > 100
        assert x["gross_expectancy_bps"] > 0          # positive drift is caught
        assert x["net_expectancy_bps"] < 0            # ...but far below the gate

def test_harness_zero_drift_gross_neutral(tmp_path):
    """With zero planted drift, the planted edge vanishes (sanity vs sign-fishing)."""
    _synthetic_derived(tmp_path / "z1", drift_bps=0.0)
    _synthetic_derived(tmp_path / "z2", drift_bps=0.0)
    ev.build_evidence_features([tmp_path / "z1", tmp_path / "z2"],
                               tmp_path / "featZ.parquet")
    m = load_model(ev.MODEL_PATH)
    met = ev.session_metrics(tmp_path / "featZ.parquet", m, 4.6658)
    assert len(met) == 2
    assert all(abs(x["gross_expectancy_bps"]) < 0.15 for x in met)


def test_decision_tree_fail_economically():
    agg = {"n_sessions": 10, "mean_gross_bps": 0.05, "gate_bps": 4.6658}
    v = ev.verdict(agg)
    assert v["verdict"] == "FAIL ECONOMICALLY" and v["case"] == "B"


def test_decision_tree_fail_zero():
    agg = {"n_sessions": 10, "mean_gross_bps": 0.0, "gate_bps": 4.6658}
    assert ev.verdict(agg)["verdict"] == "FAIL"


def test_decision_tree_case_c():
    agg = {"n_sessions": 10, "mean_gross_bps": 3.0, "gate_bps": 4.6658}
    v = ev.verdict(agg)
    assert v["verdict"] == "CONDITIONAL / INVESTIGATE EXECUTION"


def test_decision_tree_insufficient():
    agg = {"n_sessions": 3, "mean_gross_bps": 0.05, "gate_bps": 4.6658}
    assert ev.verdict(agg)["verdict"] == "CONDITIONAL / INSUFFICIENT OOS"


def test_aggregate_stats():
    met = [{"session": "a", "eligible_signals": 200, "gross_expectancy_bps": 0.1,
            "long_expectancy_bps": 0.2, "short_expectancy_bps": 0.05,
            "pred_max_abs_bps": 0.4, "pred_p99_abs_bps": 0.3,
            "signals_passing_gate": 0},
           {"session": "b", "eligible_signals": 300, "gross_expectancy_bps": 0.2,
            "long_expectancy_bps": 0.3, "short_expectancy_bps": 0.1,
            "pred_max_abs_bps": 0.5, "pred_p99_abs_bps": 0.35,
            "signals_passing_gate": 0}]
    a = ev.aggregate(met, 4.6658)
    assert a["n_sessions"] == 2 and abs(a["mean_gross_bps"] - 0.15) < 1e-9
    assert a["total_eligible_signals"] == 500


def test_manifest_written(tmp_path):
    ev.build_manifest()
    p = ev.EVIDENCE_OUT / "V5.1_MANIFEST.json"
    assert p.exists()
    m = json.loads(p.read_text())
    assert m["freeze_id"] and "modules" in m["body"]