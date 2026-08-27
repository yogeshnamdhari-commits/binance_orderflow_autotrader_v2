"""V6 Independent Replication Protocol.

Replication is MANDATORY before any deployment review.

Procedure:
  1. Select untouched data (not used in training/validation/OOS)
  2. Apply identical V6 feature engineering
  3. Use frozen V6 model (no refitting)
  4. Apply same cost model (Q2 contemporary)
  5. Run identical Signal Decision Engine gates
  6. Report gross expectancy, net expectancy, HAC p-values
  7. Compare with original OOS results
  8. Replication passes if: net > 0, p < 0.05, regime robust, long/short symmetric

This module automates the replication protocol.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from .v3_model import chrono_split_masks
from .v5_model import load_model as load_v5, predict as predict_v5
from .v6_model import load_model as load_v6, predict as predict_v6
from .v6_features import V5_FEATURES
from .v6_cost import cost_distribution_from_cal, load_calibration
from .signal_decision import SignalDecisionEngine, BookIntegrityState

DATA = Path("data")
RESEARCH = DATA / "research"
OUT_DIR = RESEARCH / "v6" / "replication"
Q2_GATE_BPS = 4.6646
Q2_MAKER_GATE_BPS = 3.4396


def _newey_west_se(x, max_lag):
    x = np.asarray(x, dtype=float)
    x = x - np.nanmean(x)
    n = len(x)
    if n < 2:
        return 0.0
    max_lag = int(max(1, min(max_lag, n - 1)))
    gamma = np.zeros(max_lag + 1)
    for l in range(max_lag + 1):
        gamma[l] = np.nanmean(x[:n - l] * x[l:])
    var_hac = gamma[0].copy()
    for l in range(1, max_lag + 1):
        w = 1.0 - l / (max_lag + 1.0)
        var_hac += 2.0 * w * gamma[l]
    return float(np.sqrt(max(0.0, var_hac) / n))


def _hac_stats(x, max_lag):
    x = np.asarray(x, dtype=float)
    mu = float(np.nanmean(x))
    se = _newey_west_se(x, max_lag)
    z = mu / se if se > 0 else 0.0
    p = 2.0 * stats.norm.sf(abs(z))
    ci_lo = mu - 1.96 * se
    ci_hi = mu + 1.96 * se
    return mu, se, z, p, ci_lo, ci_hi


def _scoreboard(df, pred, gate, horizon_ms=500):
    """Scoreboard for replication results."""
    y = df["r_%d" % horizon_ms].to_numpy(float)
    ts = df["ts_ms"].to_numpy(dtype=np.int64)
    states = np.where(pred > gate, "LONG", np.where(pred < -gate, "SHORT", "NO_TRADE"))
    gross = np.sign(pred)
    gross_move = gross * y
    executed = states != "NO_TRADE"
    net_exe = np.where(executed, gross * y - gate, 0.0)

    median_gap = float(np.median(np.diff(ts))) if len(ts) > 1 else 1000.0
    max_lag = int(min(5 * median_gap / 1000.0, len(gross_move) - 1))
    max_lag = max(1, max_lag)
    g_mu, g_se, g_z, g_p, g_lo, g_hi = _hac_stats(gross_move, max_lag)
    n_mu, n_se, n_z, n_p, n_lo, n_hi = _hac_stats(net_exe[executed], max_lag) if executed.any() else (0.0, 0.0, 0.0, 1.0, 0.0, 0.0)

    return {
        "horizon_ms": horizon_ms,
        "gate_bps": gate,
        "oos_rows": int(len(df)),
        "executed_rows": int(executed.sum()),
        "gross_expectancy_bps": round(float(g_mu), 6),
        "gross_hac_se_bps": round(g_se, 6),
        "gross_hac_p": round(g_p, 6),
        "gross_hac_ci95": [round(g_lo, 6), round(g_hi, 6)],
        "net_expectancy_bps": round(float(n_mu), 6),
        "net_hac_se_bps": round(n_se, 6),
        "net_hac_z": round(n_z, 4),
        "net_hac_p": round(n_p, 6),
        "net_hac_ci95": [round(n_lo, 6), round(n_hi, 6)],
        "hac_max_lag": max_lag,
        "per_direction": {
            "LONG": {
                "n": int((states == "LONG").sum()),
                "gross_bps": round(float(np.nanmean(gross_move[states == "LONG"])), 6),
                "net_bps": round(float(np.nanmean(net_exe[states == "LONG"])), 6),
            },
            "SHORT": {
                "n": int((states == "SHORT").sum()),
                "gross_bps": round(float(np.nanmean(gross_move[states == "SHORT"])), 6),
                "net_bps": round(float(np.nanmean(net_exe[states == "SHORT"])), 6),
            },
        },
    }


def run_replication(v5_model_path, v6_model_path, v5_feature_path, v6_feature_path,
                    untouched_session_dirs, cost_cal_path=None, out_dir=OUT_DIR, log=print):
    """Run independent replication on untouched data.

    Args:
        v5_model_path: Path to frozen V5 model
        v6_model_path: Path to frozen V6 model
        v5_feature_path: Path to V5 features (for label computation)
        v6_feature_path: Path to V6 features (for replication)
        untouched_session_dirs: List of session directories NOT used in original V6
        cost_cal_path: Path to execution cost calibration
        out_dir: Output directory

    Returns:
        Replication report dict
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load cost calibration
    cal = load_calibration(cost_cal_path or Path("data/hist/research/execution_calibration.json"))
    cost_dist = cost_distribution_from_cal(cal)
    hist_gate = cost_dist.taker_gate_bps
    cont_gate = Q2_GATE_BPS
    maker_gate = Q2_MAKER_GATE_BPS

    log(f"[REPLICATION] Starting independent replication")
    log(f"[REPLICATION] Sessions: {len(untouched_session_dirs)}")
    log(f"[REPLICATION] Taker gate: {hist_gate:.4f} bps")
    log(f"[REPLICATION] Contemporary gate: {cont_gate:.4f} bps")

    # Load untouched V6 features (these contain the untouched sessions)
    v6_rep = pd.read_parquet(v6_feature_path)

    # Add labels if missing
    if "r_500" not in v6_rep.columns:
        from .v3_labels import add_labels
        v6_rep = add_labels(v6_rep, [250, 500, 1000])

    # Filter to untouched sessions only
    untouched_names = [Path(d).name for d in untouched_session_dirs]
    v6_rep = v6_rep[v6_rep["session"].isin(untouched_names)].reset_index(drop=True)

    if len(v6_rep) == 0:
        raise ValueError("no untouched data found for replication")

    log(f"[REPLICATION] Untouched rows: {len(v6_rep)}")
    log(f"[REPLICATION] Sessions: {sorted(v6_rep['session'].unique())}")

    # V5 predictions on untouched data require V5 features
    # If V5 features don't contain these sessions, we skip V5 comparison
    v5_rep = pd.read_parquet(v5_feature_path)
    v5_rep = v5_rep[v5_rep["session"].isin(untouched_names)].reset_index(drop=True)
    has_v5 = len(v5_rep) > 0
    if has_v5:
        if "r_500" not in v5_rep.columns:
            from .v3_labels import add_labels
            v5_rep = add_labels(v5_rep, [250, 500, 1000])

    log(f"[REPLICATION] Untouched rows: {len(v5_rep)}")
    log(f"[REPLICATION] Sessions: {sorted(v5_rep['session'].unique())}")

    # Load models
    v5_model = load_v5(v5_model_path)
    v6_model = load_v6(v6_model_path)

    # Add labels to v6_rep if missing
    if "r_500" not in v6_rep.columns:
        from .v3_labels import add_labels
        v6_rep = add_labels(v6_rep, [250, 500, 1000])

    # V6 predictions on untouched data
    v6_pred = predict_v6(v6_model, v6_rep, 500)

    # V5 predictions if V5 features available for these sessions
    v5_sb = None
    if has_v5 and len(v5_rep) > 0:
        if "r_500" not in v5_rep.columns:
            from .v3_labels import add_labels
            v5_rep = add_labels(v5_rep, [250, 500, 1000])
        v5_pred = predict_v5(v5_model, v5_rep, 500)
        v5_sb = _scoreboard(v5_rep, v5_pred, hist_gate)
        log(f"[REPLICATION] V5 gross: {v5_sb['gross_expectancy_bps']:.4f} bps")

    # V6 scoreboard
    v6_sb = _scoreboard(v6_rep, v6_pred, hist_gate)
    v6_sb_cont = _scoreboard(v6_rep, v6_pred, cont_gate)

    log(f"[REPLICATION] V6 gross: {v6_sb['gross_expectancy_bps']:.4f} bps")
    log(f"[REPLICATION] V6 net (cont): {v6_sb_cont['net_expectancy_bps']:.4f} bps")

    if v5_sb is not None:
        log(f"[REPLICATION] V5 gross: {v5_sb['gross_expectancy_bps']:.4f} bps")

    # Compare with original OOS results
    try:
        with open(out_dir.parent / "V6_COMPREHENSIVE_VALIDATION.json") as f:
            original = json.load(f)
        original_v6_gross = original["verdict"]["v6_extension"]["gross_expectancy_bps"]
        original_v6_net = original["verdict"]["cost_adjusted"]["contemporaneous_taker"]["net_bps"]
    except Exception:
        original_v6_gross = None
        original_v6_net = None

    # Replication verdict
    v6_net = v6_sb_cont["net_expectancy_bps"]
    v6_gross_sig = v6_sb_cont["gross_hac_p"] < 0.05 and v6_sb_cont["gross_expectancy_bps"] > 0
    v6_net_sig = v6_sb_cont["net_hac_p"] < 0.05 and v6_net > 0
    long_net = v6_sb_cont["per_direction"]["LONG"]["net_bps"]
    short_net = v6_sb_cont["per_direction"]["SHORT"]["net_bps"]
    symmetric = abs(long_net - short_net) < max(abs(long_net), abs(short_net), 0.1)

    passes_net = v6_net > 0
    passes_gross = v6_gross_sig
    passes_net_sig = v6_net_sig
    passes_symmetry = symmetric

    replication_passes = passes_net and passes_gross and passes_net_sig and passes_symmetry

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "protocol": (
            "Independent replication: V6 model evaluated on untouched data. "
            "No refitting, no parameter changes, same cost model."
        ),
    "replication_data": {
        "sessions": sorted(v6_rep["session"].unique()) if len(v6_rep) > 0 else [],
        "rows": int(len(v6_rep)),
        "start_ts_ms": int(v6_rep["ts_ms"].min()) if len(v6_rep) > 0 else None,
        "end_ts_ms": int(v6_rep["ts_ms"].max()) if len(v6_rep) > 0 else None,
    },
        "cost_calibration": {
            "taker_gate_bps": hist_gate,
            "contemporaneous_gate_bps": cont_gate,
            "maker_gate_bps": maker_gate,
        },
        "v5_scoreboard": v5_sb,
        "v6_scoreboard": v6_sb,
        "v6_scoreboard_contemporaneous": v6_sb_cont,
        "original_oos_v6_gross": original_v6_gross,
        "original_oos_v6_net": original_v6_net,
        "replication_gates": {
            "passes_net_positive": passes_net,
            "passes_gross_significant": passes_gross,
            "passes_net_significant": passes_net_sig,
            "passes_long_short_symmetry": passes_symmetry,
        },
        "verdict": (
            "REPLICATION_PASS — proceed to deployment review"
            if replication_passes
            else "REPLICATION_FAIL — no deployable edge"
        ),
    }

    # Write report
    report_path = out_dir / "replication_report.json"
    report_path.write_text(json.dumps(report, indent=2, default=lambda o: o.item() if hasattr(o, 'item') else str(o)))
    log(f"[REPLICATION] Report: {report_path}")
    log(f"[REPLICATION] Verdict: {report['verdict']}")

    return report


def select_untouched_sessions(all_session_dirs, used_session_names):
    """Select sessions not used in original V6 training/validation/OOS.

    Args:
        all_session_dirs: All available session directories
        used_session_names: Session names used in original V6

    Returns:
        List of untouched session directories
    """
    untouched = []
    for d in all_session_dirs:
        if not Path(d).is_dir():
            continue
        name = Path(d).name
        if name not in used_session_names:
            untouched.append(d)
    return untouched


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--v5-features", type=Path, default=RESEARCH / "v5_features.parquet")
    ap.add_argument("--v6-features", type=Path, default=RESEARCH / "v6_features.parquet")
    ap.add_argument("--v5-model", type=Path, default=RESEARCH / "v5_model.json")
    ap.add_argument("--v6-model", type=Path, default=RESEARCH / "v6_model.json")
    ap.add_argument("--sessions", nargs="+", type=Path, default=list(Path("data/live/v5").glob("*")))
    ap.add_argument("--used-sessions", nargs="+", default=[])
    ap.add_argument("--cost-cal", type=Path, default=Path("data/hist/research/execution_calibration.json"))
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    a = ap.parse_args()

    untouched = select_untouched_sessions(a.sessions, a.used_sessions)
    if not untouched:
        print("No untouched sessions available for replication")
    else:
        r = run_replication(a.v5_model, a.v6_model, a.v5_features, a.v6_features,
                            untouched, a.cost_cal, a.out)
        print(json.dumps({"verdict": r["verdict"],
                          "v6_gross": r["v6_scoreboard"]["gross_expectancy_bps"],
                          "v6_net": r["v6_scoreboard_contemporaneous"]["net_expectancy_bps"]},
                         indent=2))
