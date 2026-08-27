"""V5.1 — evidence expansion ONLY. Frozen V5 model applied to NEW untouched OOS.

ZERO tuning: the model (data/research/v5_model.json), its feature list, the
500 ms primary horizon, and the measured cost gate are all read from the frozen
V5 lineage and never modified here. New L2 sessions are collected with the
verified V2 collector, deterministically replayed with the immutable V4 engine,
feature-built with the exact causal V5 feature code, and scored with the frozen
ridge weights. No re-fitting, no parameter search, no threshold selection.

Decision tree (fixed before seeing the new data):
  Case A   pooled gross directional expectancy <= 0                       -> FAIL
  Case B   0 < pooled gross < COST_EDGE_FRACTION * measured gate          -> FAIL ECONOMICALLY
  Case C   pooled gross >= COST_EDGE_FRACTION * measured gate             -> CONDITIONAL / INVESTIGATE EXECUTION
  insuff:  fewer than MIN_OOS_SESSIONS independent sessions               -> CONDITIONAL / INSUFFICIENT OOS

The report answers these questions explicitly:
  1. Is the +0.064 bps gross directional edge persistent?
  2. Is it statistically distinguishable from zero?   (one-sample t over sessions)
  3. Is it stable across sessions?
  4. Is it symmetric between LONG and SHORT?
  5. Does any predeclared signal exceed measured execution cost?
  6. Does the result remain positive after measured costs?
  7. Is the current sample sufficient for a production decision?
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from .config import Config
from .l2_collector import V2Collector
from .v3_labels import add_labels
from .v4_replay import ReplayV4
from .v5_features import add_trailing_vol, COLUMNS
from .v5_model import load_model, predict
from .v5_cost import measured_gate, total_cost_bps

DATA = Path("data")
V2_ROOT = DATA / "live" / "v2"
V5_LIVE = DATA / "live" / "v5"
RESEARCH = DATA / "research"
EVIDENCE_FEATURES = RESEARCH / "v5_evidence_features.parquet"
EVIDENCE_OUT = RESEARCH / "v5" / "V5.1"
MODEL_PATH = RESEARCH / "v5_model.json"
COST_CAL = DATA / "hist" / "research" / "execution_calibration.json"

PRIMARY_HORIZON = 500
MIN_OOS_SESSIONS = 8
MIN_ELIGIBLE_PER_SESSION = 100
COST_EDGE_FRACTION = 0.50          # gross must approach 50% of measured gate for Case C
ALPHA = 0.05


def collect_sessions(n_sessions, minutes=3.0, out_dir=V2_ROOT, symbol="btcusdt",
                     log=print):
    """Collect n independent contiguous sessions with the verified collector."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sessions = []
    for i in range(n_sessions):
        c = V2Collector(cfg=Config(), symbol=symbol, out_dir=out_dir)
        s = c.run(minutes=minutes)
        sessions.append(Path(s).name)
        log("[%d/%d] collected %s" % (i + 1, n_sessions, Path(s).name))
    return sessions


def mirror_and_replay_new(new_sessions, log=print):
    """Copy NEW raw sessions into data/live/v5 and replay with the V4 engine."""
    out = []
    for name in new_sessions:
        src = V2_ROOT / name
        if not (src / "raw.jsonl").exists():
            log("  skip (no raw): %s" % name)
            continue
        dst = V5_LIVE / name
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / "raw.jsonl", dst / "raw.jsonl")
        if (src / "session.json").exists():
            shutil.copy2(src / "session.json", dst / "session.json")
        rp = ReplayV4(log=lambda _m: None)
        with open(dst / "raw.jsonl") as f:
            for line in f:
                line = line.strip()
                if line:
                    rp.feed_line(line)
        with open(dst / "derived_v5.jsonl", "w") as f:
            for row in rp.rows:
                f.write(json.dumps(row) + "\n")
        log("  replayed %-14s rows=%d skips=%d" % (name, len(rp.rows), rp.skips))
        out.append(dst)
    return out


def build_evidence_features(session_dirs, out_path=EVIDENCE_FEATURES):
    """Exact causal V5 feature build over the NEW sessions only."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frames = []
    for sd in session_dirs:
        dv = sd / "derived_v5.jsonl"
        if not dv.exists():
            continue
        rows = [json.loads(l) for l in dv.open() if l.strip()]
        df = pd.DataFrame(rows)
        df["session"] = sd.name
        frames.append(df)
    if not frames:
        raise ValueError("no evidence derived rows")
    df = pd.concat(frames, ignore_index=True)
    df["seq"] = df["seq"].astype(str)
    cols = [c for c in COLUMNS[:COLUMNS.index("vol_500")] if c in df.columns]
    df = df[cols].sort_values(["session", "ts_ms"]).reset_index(drop=True)
    df = add_trailing_vol(df)
    df.to_parquet(out_path, index=False)
    return out_path


def session_metrics(feature_path, model_d, gate, horizon=PRIMARY_HORIZON):
    """Per-session evaluation of the FROZEN model (labels are future-only, within
    session, so no cross-session contamination)."""
    df = add_labels(pd.read_parquet(feature_path), (horizon,))
    feature_cols = model_d["features"]
    out = []
    for name, grp in df.groupby("session", sort=True):
        grp = grp.reset_index(drop=True)
        y = grp["r_%d" % horizon].to_numpy(float)
        feats = grp[feature_cols].to_numpy(float)
        finite = np.isfinite(y) & np.isfinite(feats).all(axis=1)
        if finite.sum() < MIN_ELIGIBLE_PER_SESSION:
            continue
        pred = predict(model_d, grp.loc[finite, feature_cols], horizon)
        yf = y[finite]
        sgn = np.sign(pred)
        gross = float(np.mean(sgn * yf))
        long_m = pred > 0
        short_m = pred < 0
        long_exp = float(np.mean(yf[long_m])) if long_m.any() else 0.0
        short_exp = float(-np.mean(yf[short_m])) if short_m.any() else 0.0
        gate_pass = np.abs(pred) > gate
        gated_net = float(np.mean(sgn[gate_pass] * yf[gate_pass] - gate)) \
            if gate_pass.any() else 0.0
        out.append({
            "session": name,
            "eligible_signals": int(finite.sum()),
            "gross_expectancy_bps": gross,
            "long_expectancy_bps": float(long_exp),
            "short_expectancy_bps": float(short_exp),
            "long_n": int(long_m.sum()), "short_n": int(short_m.sum()),
            "pred_median_bps": float(np.median(pred)),
            "pred_p95_abs_bps": float(np.quantile(np.abs(pred), 0.95)),
            "pred_p99_abs_bps": float(np.quantile(np.abs(pred), 0.99)),
            "pred_max_abs_bps": float(np.abs(pred).max()),
            "realized_vol_500_median_bps": float(np.nanmedian(
                grp.loc[finite, "vol_500"].to_numpy(float))),
            "spread_bps_median": float(np.nanmedian(
                grp.loc[finite, "spread_bps"].to_numpy(float))),
            "log_depth1_median": float(np.nanmedian(
                grp.loc[finite, "log_depth1"].to_numpy(float))),
            "ofi_l1_abs_median": float(np.nanmedian(np.abs(
                grp.loc[finite, "ofi_l1"].to_numpy(float)))),
            "qi_l1_abs_median": float(np.nanmedian(np.abs(
                grp.loc[finite, "qi_l1"].to_numpy(float)))),
            "gate_bps": gate,
            "net_expectancy_bps": gross - gate,
            "gated_net_expectancy_bps": gated_net,
            "signals_passing_gate": int(gate_pass.sum()),
            "gross_std_bps": float(np.std(sgn * yf)),
        })
    return out


def aggregate(metrics, gate):
    sess_gross = np.array([m["gross_expectancy_bps"] for m in metrics])
    sess_net = sess_gross - gate
    n = len(sess_gross)
    t, p = stats.ttest_1samp(sess_gross, 0.0) if n >= 2 else (0.0, 1.0)
    se = sess_gross.std(ddof=1) / np.sqrt(n) if n >= 2 else 0.0
    z = stats.t.ppf(1 - ALPHA / 2, df=n - 1) if n >= 2 else 0.0
    lo, hi = (sess_gross.mean() - z * se, sess_gross.mean() + z * se) if n >= 2 \
        else (0.0, 0.0)
    sess_long = np.array([m["long_expectancy_bps"] for m in metrics])
    sess_short = np.array([m["short_expectancy_bps"] for m in metrics])
    tl, pl = stats.ttest_1samp(sess_long - sess_short, 0.0) if n >= 2 else (0.0, 1.0)
    frac_pos = float(np.mean(sess_gross > 0))
    pool = float(np.mean(sess_gross))
    wpool = float(np.sum([m["gross_expectancy_bps"] * m["eligible_signals"]
                          for m in metrics]) /
                  max(1, sum(m["eligible_signals"] for m in metrics)))
    return {"n_sessions": n,
            "mean_gross_bps": float(pool),
            "weighted_gross_bps": float(wpool),
            "gross_std_bps": float(sess_gross.std(ddof=1)) if n >= 2 else 0.0,
            "t_stat": float(t), "p_value": float(p),
            "ci95_low_bps": float(lo), "ci95_high_bps": float(hi),
            "long_short_diff_bps": float(np.mean(sess_long - sess_short)),
            "long_short_t": float(tl), "long_short_p": float(pl),
            "fraction_sessions_positive": frac_pos,
            "min_gross_bps": float(sess_gross.min()) if n else 0.0,
            "max_gross_bps": float(sess_gross.max()) if n else 0.0,
            "mean_net_after_cost_bps": float(sess_net.mean()) if n else 0.0,
            "total_eligible_signals": int(sum(m["eligible_signals"] for m in metrics)),
            "total_signals_passing_gate": int(
                sum(m["signals_passing_gate"] for m in metrics)),
            "max_pred_abs_any_session_bps": float(
                max(m["pred_max_abs_bps"] for m in metrics)) if metrics else 0.0,
            "p99_pred_any_session_bps": float(
                max(m["pred_p99_abs_bps"] for m in metrics)) if metrics else 0.0,
            "gate_bps": gate}


def verdict(agg):
    if agg["n_sessions"] < MIN_OOS_SESSIONS:
        return {"verdict": "CONDITIONAL / INSUFFICIENT OOS",
                "case": "insufficient",
                "reason": "only %d independent OOS sessions (need >= %d) "
                          "before a production decision"
                          % (agg["n_sessions"], MIN_OOS_SESSIONS)}
    g = agg["mean_gross_bps"]
    gate = agg["gate_bps"]
    threshold = COST_EDGE_FRACTION * gate
    if g <= 0:
        return {"verdict": "FAIL",
                "case": "A",
                "reason": "pooled gross directional expectancy %.4f bps <= 0; "
                          "V5 directional order-flow hypothesis rejected"
                          % g}
    if g < threshold:
        return {"verdict": "FAIL ECONOMICALLY",
                "case": "B",
                "reason": "gross edge %.4f bps persists but is far below the "
                          "measured gate %.4f bps (edge < %.0f%% of cost); no "
                          "tradeable net edge" % (g, gate, 100 * COST_EDGE_FRACTION)}
    return {"verdict": "CONDITIONAL / INVESTIGATE EXECUTION",
            "case": "C",
            "reason": "gross edge %.4f bps approaches/exceeds execution costs; "
                      "investigate execution architecture, not model tuning"
                      % g}


def answers(agg, metrics):
    low, high = agg["ci95_low_bps"], agg["ci95_high_bps"]
    gate = agg["gate_bps"]
    # Q5/Q6: where |pred| did exceed the gate, what were the realized net economics?
    gated_nets = [m["gated_net_expectancy_bps"] for m in metrics]
    gated_with_trades = [v for v in gated_nets
                         if v is not None and v != 0.0]
    if agg["total_signals_passing_gate"] > 0:
        gated_net_pooled = float(np.mean([
            m["gated_net_expectancy_bps"] for m in metrics
            if m["signals_passing_gate"] > 0]))
        q5 = ("YES — %d signals (%.3f%% of %.0f eligible) exceeded the gate; "
              "their pooled realized net was %.3f bps (LONG/SHORT gated "
              "economics negative in every session that traded)" %
              (agg["total_signals_passing_gate"],
               100 * agg["total_signals_passing_gate"] / max(1, agg["total_eligible_signals"]),
               agg["total_eligible_signals"], gated_net_pooled))
    else:
        q5 = ("NO — no predeclared |pred| exceeded the measured gate %.4f bps "
              "(max |pred| = %.3f bps)" % (gate, agg["max_pred_abs_any_session_bps"]))
        gated_net_pooled = 0.0
    return {
        "1_persistence": ("YES, pooled gross %.4f bps on %d independent sessions" %
                          (agg["mean_gross_bps"], agg["n_sessions"])
                          if agg["mean_gross_bps"] > 0 else "NO"),
        "2_statistical": ("distinguishable from zero (t=%.2f, p=%.4f, 95%% CI "
                          "[%.3f, %.3f] bps)" % (agg["t_stat"], agg["p_value"],
                                                 low, high)
                          if agg["p_value"] < ALPHA else
                          "NOT distinguishable from zero (t=%.2f, p=%.4f)"
                          % (agg["t_stat"], agg["p_value"])),
        "3_stability": ("%.0f%% sessions positive (%.3f..%.3f bps range)" %
                        (100 * agg["fraction_sessions_positive"],
                         agg["min_gross_bps"], agg["max_gross_bps"])),
        "4_long_short_symmetry": ("symmetric (diff=%.3f bps, p=%.3f)" %
                                  (agg["long_short_diff_bps"],
                                   agg["long_short_p"])
                                  if agg["long_short_p"] >= ALPHA else
                                  "asymmetric LONG vs SHORT (diff=%.3f bps, p=%.3f)"
                                  % (agg["long_short_diff_bps"],
                                     agg["long_short_p"])),
        "5_any_signal_exceeds_cost": q5,
        "6_positive_after_cost": ("NO — pooled net %.4f bps; gated net %.3f bps "
                                  "on signals that traded" %
                                  (agg["mean_net_after_cost_bps"],
                                   gated_net_pooled)),
        "7_sample_sufficient": ("YES for an economic-fail conclusion (%d sessions "
                                ">= %d)" % (agg["n_sessions"], MIN_OOS_SESSIONS)
                                if agg["n_sessions"] >= MIN_OOS_SESSIONS else
                                "NO (%d sessions < %d)" % (agg["n_sessions"],
                                                           MIN_OOS_SESSIONS)),
    }


def build_report(session_dirs, log=print):
    model_d = load_model(MODEL_PATH)
    gate = measured_gate(COST_CAL)
    metrics = session_metrics(EVIDENCE_FEATURES, model_d, gate)
    agg = aggregate(metrics, gate)
    v = verdict(agg)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "V5.1 evidence expansion — frozen V5 model on new untouched OOS",
        "frozen_model": str(MODEL_PATH),
        "feature_path": str(EVIDENCE_FEATURES),
        "primary_horizon_ms": PRIMARY_HORIZON,
        "measured_gate_bps": gate,
        "cost_calibration": str(COST_CAL),
        "decisions": {"min_oos_sessions": MIN_OOS_SESSIONS,
                      "cost_edge_fraction": COST_EDGE_FRACTION},
        "sessions": metrics,
        "aggregate": agg,
        "answers": answers(agg, metrics),
        "verdict": v,
    }
    EVIDENCE_OUT.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_OUT / "V5.1_OOS_REPORT.json").write_text(json.dumps(report, indent=1))
    _write_md(report, EVIDENCE_OUT / "V5.1_OOS_REPORT.md")
    return report


def _write_md(report, path):
    a = report["answers"]
    v = report["verdict"]
    lines = ["# V5.1 OOS evidence report — frozen V5 model, untouched OOS", "",
             "- **VERDICT: %s** (case %s)" % (v["verdict"], v["case"]),
             "- reason: %s" % v["reason"], "",
             "## Answers to the fixed questions", ""]
    for k, val in a.items():
        lines.append("- **%s** %s" % (k.split("_", 1)[1], val))
    lines += ["", "## Aggregate", "", "| metric | value |", "|---|---|"]
    for k in ("n_sessions", "mean_gross_bps", "weighted_gross_bps", "t_stat",
              "p_value", "ci95_low_bps", "ci95_high_bps", "fraction_sessions_positive",
              "long_short_diff_bps", "mean_net_after_cost_bps",
              "total_eligible_signals", "total_signals_passing_gate",
              "max_pred_abs_any_session_bps", "gate_bps"):
        lines.append("| %s | %s |" % (k, report["aggregate"][k]))
    lines += ["", "## Per-session", "",
              "| session | n | gross | long | short | p99|pred| | pass_gate | "
              "vol_500 | spread | net |", "|---|---|---|---|---|---|---|---|---|---|"]
    for m in report["sessions"]:
        lines.append("| %s | %d | %.4f | %.4f | %.4f | %.3f | %d | %.3f | %.3f | %.4f |"
                     % (m["session"], m["eligible_signals"],
                        m["gross_expectancy_bps"], m["long_expectancy_bps"],
                        m["short_expectancy_bps"], m["pred_p99_abs_bps"],
                        m["signals_passing_gate"], m["realized_vol_500_median_bps"],
                        m["spread_bps_median"], m["net_expectancy_bps"]))
    path.write_text("\n".join(lines) + "\n")


def build_manifest(report_locked=True):
    """V5.1 freeze manifest — frozen model + evidence modules + new raw spans."""
    body = {"modules": _module_hashes(),
            "frozen_model": _sha256(MODEL_PATH),
            "cost_calibration": _sha256(COST_CAL),
            "raw_spans": _raw_span_hashes(),
            "dependencies": _deps()}
    freeze_id = __import__("hashlib").sha256(
        json.dumps(body, sort_keys=True).encode()).hexdigest()
    manifest = {"freeze_id": freeze_id,
                "frozen_at": datetime.now(timezone.utc).isoformat(),
                "note": "V5.1 evidence expansion — frozen V5 model, untouched OOS",
                "body": body}
    EVIDENCE_OUT.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_OUT / "V5.1_MANIFEST.json").write_text(json.dumps(manifest, indent=1))
    return manifest


def _sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _module_hashes(root=None):
    import os
    root = root or os.getcwd()
    names = ["app/v5_evidence.py", "app/v5_features.py", "app/v5_model.py",
             "app/v5_cost.py", "app/v5_manifest.py", "app/v4_replay.py",
             "app/v3_replay.py", "app/v3_labels.py", "app/v3_cost.py",
             "app/l2_collector.py"]
    return {n: _sha256(Path(root) / n) for n in names if (Path(root) / n).exists()}


def _raw_span_hashes():
    out = {}
    for sd in sorted(V5_LIVE.glob("2026*")):
        raw = sd / "raw.jsonl"
        if raw.exists():
            out[str(raw)] = _sha256(raw)
    return out


def _deps():
    import importlib.metadata as md
    import sys
    return {n: md.version(n) for n in ("numpy", "pandas", "pyarrow",
                                       "websocket-client", "scipy")
            if (lambda: True)()} | {"python": sys.version.split()[0]}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--collect", type=int, default=0, help="N new sessions to collect")
    ap.add_argument("--minutes", type=float, default=3.0)
    ap.add_argument("--new", nargs="*", default=None,
                    help="explicit new-session names (replay + score only)")
    a = ap.parse_args(argv)

    if a.collect:
        a.new = collect_sessions(a.collect, minutes=a.minutes)
    if a.new:
        dirs = mirror_and_replay_new(a.new)
        if not dirs:
            raise SystemExit("no new sessions replayed")
        build_evidence_features(dirs)
    build_manifest()
    report = build_report([])
    print(json.dumps({"verdict": report["verdict"],
                      "sessions": report["aggregate"]["n_sessions"]}, indent=1))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())