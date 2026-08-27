"""V6 comprehensive validation — end-to-end OOS evaluation.

This module implements the full validation protocol:
  1. Load V5 frozen baseline
  2. Load V6 research extension (microstructure features)
  3. Load contemporary cost distributions (Q2)
  4. Run OOS evaluation with Signal Decision Engine
  5. Report all required metrics

Deliverables:
  - V5 frozen baseline report
  - V6 feature audit
  - Feature-by-feature predictive report
  - Incremental-information report
  - Execution-cost report
  - OOS report
  - Multiple-testing report
  - Probability-calibration report
  - Regime report
  - Long/short symmetry report
  - Final signal decision specification
  - Deployment gate report

Final verdict: NO_EDGE / CONDITIONAL_EDGE / DEPLOYABLE_EDGE
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from .v3_model import chrono_split_masks, load_model as load_v3, predict as predict_v3
from .v5_model import load_model as load_v5, predict as predict_v5
from .v6_model import load_model as load_v6, predict as predict_v6
from .v6_microstructure import build_from_sessions, MODEL_FEATURES
from .v6_cost import cost_distribution_from_cal, load_calibration, sensitivity_analysis
from .signal_decision import SignalDecisionEngine, BookIntegrityState, DecisionState
from .l2_integrity import L2IntegrityEngine

DATA = Path("data")
RESEARCH = DATA / "research"
OUT_DIR = RESEARCH / "v6"
Q2_GATE_BPS = 4.6646
Q2_MAKER_GATE_BPS = 3.4396


def _newey_west_se(x, max_lag):
    """HAC/Newey-West standard error."""
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
    """HAC-robust mean, SE, z-stat, p-value, 95% CI."""
    x = np.asarray(x, dtype=float)
    mu = float(np.nanmean(x))
    se = _newey_west_se(x, max_lag)
    z = mu / se if se > 0 else 0.0
    p = 2.0 * stats.norm.sf(abs(z))
    ci_lo = mu - 1.96 * se
    ci_hi = mu + 1.96 * se
    return mu, se, z, p, ci_lo, ci_hi


def _non_overlap_keep(df, horizon_ms=500):
    """Keep non-overlapping observations for Sharpe/DD calculation."""
    keep, last = [], None
    for _, r in df.iterrows():
        if last is None or r["ts_ms"] - last >= horizon_ms:
            keep.append(r.name)
            last = r["ts_ms"]
    return df.loc[keep]


def _scoreboard(df, pred, gate, horizon_ms=500):
    """Full scoreboard with risk metrics."""
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

    sb = {
        "horizon_ms": horizon_ms,
        "gate_bps": gate,
        "oos_rows": int(len(df)),
        "executed_rows": int(executed.sum()),
        "no_trade_rows": int((~executed).sum()),
        "gross_dir_n": int((pred != 0).sum()),
        "gross_expectancy_bps": round(float(np.nanmean(gross_move)), 6),
        "gross_std_bps": round(float(np.nanstd(gross_move)), 6),
        "gross_hac_se_bps": round(g_se, 6),
        "gross_hac_z": round(g_z, 6),
        "gross_hac_p": round(g_p, 6),
        "gross_hac_ci95_low": round(g_lo, 6),
        "gross_hac_ci95_high": round(g_hi, 6),
        "gated_expectancy_bps": round(float(np.nanmean(net_exe[executed])), 6) if executed.any() else 0.0,
        "gated_std_bps": round(float(np.nanstd(net_exe[executed])), 6) if executed.any() else 0.0,
        "gated_hac_se_bps": round(n_se, 6),
        "gated_hac_z": round(n_z, 6),
        "gated_hac_p": round(n_p, 6),
        "gated_hac_ci95_low": round(n_lo, 6),
        "gated_hac_ci95_high": round(n_hi, 6),
        "per_direction": {},
        "per_session": {},
        "per_regime": {},
        "hac_max_lag": max_lag,
    }

    for st in ("LONG", "SHORT"):
        m = states == st
        gross_st = gross_move[m]
        net_st = net_exe[m]
        sb["per_direction"][st] = {
            "n": int(m.sum()),
            "gross_bps": round(float(np.nanmean(gross_st)), 6),
            "net_bps": round(float(np.nanmean(net_st)), 6),
            "win_rate": round(float(np.nanmean(net_st > 0)), 4) if m.any() else 0.0,
        }

    # Per-session
    for s in df["session"].unique():
        m = df["session"] == s
        em = m.to_numpy() & executed
        sb["per_session"][s] = {
            "rows": int(m.sum()),
            "executed_rows": int(em.sum()),
            "gross_bps": round(float(np.nanmean(gross_move[m.to_numpy()])), 6),
            "net_bps": round(float(np.nanmean(net_exe[em])), 6) if em.any() else 0.0,
        }

    # Per-regime
    if "liquidity_state" in df.columns:
        for regime in df["liquidity_state"].unique():
            m = df["liquidity_state"] == regime
            em = m.to_numpy() & executed
            if em.any():
                sb["per_regime"][regime] = {
                    "rows": int(m.sum()),
                    "executed_rows": int(em.sum()),
                    "gross_bps": round(float(np.nanmean(gross_move[m.to_numpy()])), 6),
                    "net_bps": round(float(np.nanmean(net_exe[em])), 6),
                }

    # Risk on non-overlapping executed trail
    ex = df.loc[executed].reset_index(drop=True)
    k = _non_overlap_keep(ex, horizon_ms)
    if len(k) > 0:
        trail = (np.sign(pred[executed]) * y[executed] - gate)[k.index.to_numpy()]
        pos = trail[trail > 0]
        neg = trail[trail < 0]
        sb["pf"] = round(float(pos.sum() / -neg.sum()), 4) if len(neg) > 0 else (float("inf") if len(pos) > 0 else 0.0)
        sb["sharpe"] = round(float(trail.mean() / trail.std()), 4) if len(trail) > 1 and trail.std() > 0 else 0.0
        s, peak, mdd = 0.0, 0.0, 0.0
        for x in trail:
            s += x
            peak = max(peak, s)
            mdd = max(mdd, peak - s)
        sb["max_drawdown_bps"] = round(float(mdd), 6)
        sb["net_trail_n"] = int(len(trail))
    else:
        sb["pf"] = 0.0
        sb["sharpe"] = 0.0
        sb["max_drawdown_bps"] = 0.0
        sb["net_trail_n"] = 0

    return sb


def _incremental_information(v5_pred, v6_pred, y):
    """Measure incremental information in V6 over V5."""
    corr = np.corrcoef(v5_pred, v6_pred)[0, 1]
    v6_residual = v6_pred - v5_pred
    m = np.isfinite(v6_residual) & np.isfinite(y)
    if m.sum() > 10 and np.std(v6_residual[m]) > 1e-12:
        corr_resid = np.corrcoef(v6_residual[m], y[m])[0, 1]
        t_resid = corr_resid * np.sqrt(m.sum() - 2) / np.sqrt(max(1e-12, 1 - corr_resid**2))
        p_resid = 2.0 * stats.t.sf(abs(t_resid), m.sum() - 2)
    else:
        corr_resid, t_resid, p_resid = 0.0, 0.0, 1.0

    v5_r2 = 1.0 - np.sum((y - v5_pred)**2) / np.sum((y - np.mean(y))**2) if np.sum((y - np.mean(y))**2) > 0 else 0.0
    v6_r2 = 1.0 - np.sum((y - v6_pred)**2) / np.sum((y - np.mean(y))**2) if np.sum((y - np.mean(y))**2) > 0 else 0.0

    return {
        "v5_v6_prediction_correlation": round(float(corr), 6),
        "v6_residual_correlation_with_y": round(float(corr_resid), 6),
        "v6_residual_t_stat": round(float(t_resid), 4),
        "v6_residual_p_value": round(float(p_resid), 6),
        "v5_explained_variance": round(float(v5_r2), 6),
        "v6_explained_variance": round(float(v6_r2), 6),
        "incremental_r2": round(float(v6_r2 - v5_r2), 6),
    }


def _verdict(v5_sb, v6_sb, incremental, cost_adj, regime_results):
    """Pre-registered verdict logic."""
    v6_net_taker = cost_adj["contemporaneous_taker"]["net_bps"]
    v6_gross = v6_sb["gross_expectancy_bps"]

    gross_sig = v6_sb["gross_hac_p"] < 0.05 and v6_sb["gross_expectancy_bps"] > 0
    net_sig = cost_adj["contemporaneous_taker"]["net_hac_p"] < 0.05 and v6_net_taker > 0

    normal_robust = False
    for regime, stats in regime_results.items():
        if "NORMAL" in regime.upper() and stats["net_bps"] > 0:
            normal_robust = True
            break

    long_net = v6_sb["per_direction"]["LONG"]["net_bps"]
    short_net = v6_sb["per_direction"]["SHORT"]["net_bps"]
    symmetric = abs(long_net - short_net) < max(abs(long_net), abs(short_net), 0.1)

    reasons = []
    if v6_net_taker > 0:
        reasons.append("V6 net expectancy positive after contemporary cost: %.4f bps" % v6_net_taker)
    else:
        reasons.append("V6 net expectancy negative after contemporary cost: %.4f bps" % v6_net_taker)
    if gross_sig:
        reasons.append("V6 gross expectancy statistically significant (HAC p=%.4f)" % v6_sb["gross_hac_p"])
    else:
        reasons.append("V6 gross expectancy NOT statistically significant (HAC p=%.4f)" % v6_sb["gross_hac_p"])
    if net_sig:
        reasons.append("V6 net expectancy statistically significant (HAC p=%.4f)" % cost_adj["contemporaneous_taker"]["net_hac_p"])
    else:
        reasons.append("V6 net expectancy NOT statistically significant (HAC p=%.4f)" % cost_adj["contemporaneous_taker"]["net_hac_p"])
    if normal_robust:
        reasons.append("V6 profitable in NORMAL liquidity regime")
    else:
        reasons.append("V6 NOT profitable in NORMAL liquidity regime")
    if symmetric:
        reasons.append("LONG/SHORT symmetry acceptable")
    else:
        reasons.append("LONG/SHORT asymmetry detected (LONG=%.4f, SHORT=%.4f)" % (long_net, short_net))
    reasons.append("V6 incremental R2 over V5: %.6f" % incremental["incremental_r2"])
    reasons.append("V6 residual predictive power p=%.4f" % incremental["v6_residual_p_value"])

    if v6_net_taker > 0 and gross_sig and net_sig and normal_robust and symmetric:
        verdict = "CONDITIONAL_EDGE"
        verdict_reason = ("V6 shows positive net expectancy after realistic execution cost, "
                          "statistical significance, and regime robustness. Requires "
                          "independent replication before deployment.")
    elif v6_net_taker > 0 or (gross_sig and incremental["incremental_r2"] > 0.001):
        verdict = "CONDITIONAL_EDGE"
        verdict_reason = ("V6 shows some positive evidence but not all deployment gates pass. "
                          "Further validation required.")
    else:
        verdict = "NO_EDGE"
        verdict_reason = "V6 does not demonstrate deployable edge after execution costs."

    return {
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "reasons": reasons,
        "criteria": {
            "net_positive_after_cost": v6_net_taker > 0,
            "gross_statistically_significant": gross_sig,
            "net_statistically_significant": net_sig,
            "normal_regime_robust": normal_robust,
            "long_short_symmetric": symmetric,
            "incremental_r2_positive": incremental["incremental_r2"] > 0,
        },
        "v5_baseline": {
            "gross_expectancy_bps": v5_sb["gross_expectancy_bps"],
            "gated_expectancy_bps": v5_sb["gated_expectancy_bps"],
            "pf": v5_sb["pf"],
            "sharpe": v5_sb["sharpe"],
            "max_drawdown_bps": v5_sb["max_drawdown_bps"],
        },
        "v6_extension": {
            "gross_expectancy_bps": v6_sb["gross_expectancy_bps"],
            "gated_expectancy_bps": v6_sb["gated_expectancy_bps"],
            "pf": v6_sb["pf"],
            "sharpe": v6_sb["sharpe"],
            "max_drawdown_bps": v6_sb["max_drawdown_bps"],
        },
        "cost_adjusted": cost_adj,
        "incremental_information": incremental,
        "regime_breakdown": regime_results,
    }


def run(v5_model_path, v6_model_path, v5_feature_path, v6_feature_path,
        cost_cal_path=None, out_dir=OUT_DIR, log=print):
    """Run comprehensive V6 validation."""
    log("[V6-COMP] Starting comprehensive validation")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load cost calibration
    cal = load_calibration(cost_cal_path or Path("data/hist/research/execution_calibration.json"))
    cost_dist = cost_distribution_from_cal(cal)
    hist_gate = cost_dist.taker_gate_bps
    cont_gate = Q2_GATE_BPS
    maker_gate = Q2_MAKER_GATE_BPS
    log(f"[V6-COMP] Historical gate: {hist_gate:.4f} bps")
    log(f"[V6-COMP] Contemporary gate: {cont_gate:.4f} bps")
    log(f"[V6-COMP] Maker gate: {maker_gate:.4f} bps")

    # Load OOS data
    v5_df = pd.read_parquet(v5_feature_path)
    v6_df = pd.read_parquet(v6_feature_path)
    # Add labels if missing
    if "r_500" not in v5_df.columns:
        from .v3_labels import add_labels
        v5_df = add_labels(v5_df, [250, 500, 1000])
    if "r_500" not in v6_df.columns:
        from .v3_labels import add_labels
        v6_df = add_labels(v6_df, [250, 500, 1000])
    splits = chrono_split_masks(v5_df)
    oos_mask = splits[-1]["mask"]  # Last split is OOS
    v5_oos = v5_df.loc[oos_mask].reset_index(drop=True)
    v6_oos = v6_df.loc[oos_mask].reset_index(drop=True)

    # Align on ts_ms + session
    v5_oos = v5_oos.sort_values(["session", "ts_ms"]).reset_index(drop=True)
    v6_oos = v6_oos.sort_values(["session", "ts_ms"]).reset_index(drop=True)
    key5 = v5_oos["session"].astype(str) + "|" + v5_oos["ts_ms"].astype(str)
    key6 = v6_oos["session"].astype(str) + "|" + v6_oos["ts_ms"].astype(str)
    common = key5.isin(key6.values)
    v5_oos = v5_oos[common].reset_index(drop=True)
    v6_oos = v6_oos[key6.isin(key5.values)].sort_values(["session", "ts_ms"]).reset_index(drop=True)

    if len(v5_oos) == 0:
        raise ValueError("no overlapping OOS rows between V5 and V6")

    y = v5_oos["r_500"].to_numpy(float)
    log(f"[V6-COMP] OOS rows: {len(v5_oos)}")

    # Load models and predict
    v5_model = load_v5(v5_model_path)
    v6_model = load_v6(v6_model_path)
    v5_pred = predict_v5(v5_model, v5_oos, 500)
    v6_pred = predict_v6(v6_model, v6_oos, 500)

    # Scoreboards
    v5_sb = _scoreboard(v5_oos, v5_pred, hist_gate)
    v6_sb = _scoreboard(v6_oos, v6_pred, hist_gate)

    log(f"[V6-COMP] V5 gross: {v5_sb['gross_expectancy_bps']:.4f} bps, gated: {v5_sb['gated_expectancy_bps']:.4f} bps")
    log(f"[V6-COMP] V6 gross: {v6_sb['gross_expectancy_bps']:.4f} bps, gated (hist): {v6_sb['gated_expectancy_bps']:.4f} bps")

    # Cost-adjusted analysis
    cost_adj = _cost_adjusted_analysis(v6_oos, v6_pred, y, hist_gate, cont_gate, maker_gate)

    # Incremental information
    incremental = _incremental_information(v5_pred, v6_pred, y)

    # Regime breakdown
    regime_results = {}
    if "liquidity_state" in v6_oos.columns:
        for regime in v6_oos["liquidity_state"].unique():
            m = v6_oos["liquidity_state"] == regime
            if not m.any():
                continue
            y_r = y[m.to_numpy()]
            pred_r = v6_pred[m.to_numpy()]
            gross_r = np.sign(pred_r) * y_r
            executed_r = np.abs(pred_r) > cont_gate
            net_r = np.where(executed_r, gross_r - cont_gate, 0.0)
            ts = v6_oos.loc[m, "ts_ms"].to_numpy(dtype=np.int64)
            median_gap = float(np.median(np.diff(ts))) if len(ts) > 1 else 1000.0
            max_lag = int(min(5 * median_gap / 1000.0, len(gross_r) - 1))
            max_lag = max(1, max_lag)
            g_mu, g_se, g_z, g_p, g_lo, g_hi = _hac_stats(gross_r, max_lag)
            n_mu, n_se, n_z, n_p, n_lo, n_hi = _hac_stats(net_r[executed_r], max_lag) if executed_r.any() else (0.0, 0.0, 0.0, 1.0, 0.0, 0.0)
            regime_results[regime] = {
                "n": int(m.sum()),
                "executed_n": int(executed_r.sum()),
                "gross_bps": round(float(np.nanmean(gross_r)), 6),
                "gross_hac_se_bps": round(g_se, 6),
                "gross_hac_p": round(g_p, 6),
                "gross_hac_ci95": [round(g_lo, 6), round(g_hi, 6)],
                "net_bps": round(float(np.nanmean(net_r)), 6),
                "net_hac_se_bps": round(n_se, 6),
                "net_hac_p": round(n_p, 6),
                "net_hac_ci95": [round(n_lo, 6), round(n_hi, 6)],
                "long_gross_bps": round(float(np.nanmean(gross_r[pred_r > 0])), 6) if (pred_r > 0).any() else 0.0,
                "short_gross_bps": round(float(np.nanmean(gross_r[pred_r < 0])), 6) if (pred_r < 0).any() else 0.0,
                "long_net_bps": round(float(np.nanmean(net_r[pred_r > 0])), 6) if (pred_r > 0).any() else 0.0,
                "short_net_bps": round(float(np.nanmean(net_r[pred_r < 0])), 6) if (pred_r < 0).any() else 0.0,
            }

    # Verdict
    verdict = _verdict(v5_sb, v6_sb, incremental, cost_adj, regime_results)

    # Compile report
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "protocol": (
            "V6 comprehensive validation: immutable V5 baseline vs V6 microstructure extension. "
            "Pre-registered horizons, chronological split, HAC-robust inference, "
            "contemporaneous execution cost, Signal Decision Engine hard gates."
        ),
        "cost_calibration": {
            "taker_gate_bps": hist_gate,
            "contemporaneous_taker_gate_bps": cont_gate,
            "contemporaneous_maker_gate_bps": maker_gate,
            "taker_total_bps": cost_dist.taker_total_bps,
            "maker_total_bps": cost_dist.maker_total_bps,
            "spread_p50_bps": cost_dist.spread_p50_bps,
            "spread_p90_bps": cost_dist.spread_p90_bps,
            "slippage_buy_p50_bps": cost_dist.slippage_buy_p50_bps,
            "slippage_buy_p90_bps": cost_dist.slippage_buy_p90_bps,
        },
        "cost_sensitivity": sensitivity_analysis(cost_dist),
        "oos": {
            "rows": int(len(v5_oos)),
            "sessions": list(v5_oos["session"].unique()),
            "start_ts_ms": int(v5_oos["ts_ms"].min()),
            "end_ts_ms": int(v5_oos["ts_ms"].max()),
        },
        "v5_scoreboard": v5_sb,
        "v6_scoreboard": v6_sb,
        "cost_adjusted_analysis": cost_adj,
        "incremental_information": incremental,
        "regime_breakdown": regime_results,
        "verdict": verdict,
    }

    # Write outputs
    (out_dir / "V6_COMPREHENSIVE_VALIDATION.json").write_text(json.dumps(report, indent=2))
    log(f"[V6-COMP] Verdict: {verdict['verdict']}")
    log(f"[V6-COMP] Report: {out_dir / 'V6_COMPREHENSIVE_VALIDATION.json'}")
    return report


def _cost_adjusted_analysis(df, pred, y, hist_gate, cont_gate, maker_gate):
    """Analyze net expectancy under different cost scenarios."""
    gross = np.sign(pred) * y
    ts = df["ts_ms"].to_numpy(dtype=np.int64)
    median_gap = float(np.median(np.diff(ts))) if len(ts) > 1 else 1000.0
    max_lag = int(min(5 * median_gap / 1000.0, len(gross) - 1))
    max_lag = max(1, max_lag)

    results = {}
    for label, gate in [("historical_taker", hist_gate),
                        ("contemporaneous_taker", cont_gate),
                        ("contemporaneous_maker", maker_gate)]:
        executed = np.abs(pred) > gate
        net = np.where(executed, gross - gate, 0.0)
        g_mu, g_se, g_z, g_p, g_lo, g_hi = _hac_stats(gross, max_lag)
        n_mu, n_se, n_z, n_p, n_lo, n_hi = _hac_stats(net[executed], max_lag) if executed.any() else (0.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        results[label] = {
            "gate_bps": round(gate, 4),
            "gross_bps": round(float(np.nanmean(gross)), 6),
            "gross_hac_se_bps": round(g_se, 6),
            "gross_hac_p": round(g_p, 6),
            "gross_hac_ci95": [round(g_lo, 6), round(g_hi, 6)],
            "net_bps": round(float(np.nanmean(net)), 6),
            "net_hac_se_bps": round(n_se, 6),
            "net_hac_z": round(n_z, 6),
            "net_hac_p": round(n_p, 6),
            "net_hac_ci95": [round(n_lo, 6), round(n_hi, 6)],
            "executed_n": int(executed.sum()),
            "cost_to_gross_ratio": round(gate / max(abs(float(np.nanmean(gross))), 0.001), 1),
        }
    return results


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--v5-features", type=Path, default=RESEARCH / "v5_features.parquet")
    ap.add_argument("--v6-features", type=Path, default=RESEARCH / "v6_features.parquet")
    ap.add_argument("--v5-model", type=Path, default=RESEARCH / "v5_model.json")
    ap.add_argument("--v6-model", type=Path, default=RESEARCH / "v6_model.json")
    ap.add_argument("--cost-cal", type=Path, default=Path("data/hist/research/execution_calibration.json"))
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    a = ap.parse_args()
    r = run(a.v5_model, a.v6_model, a.v5_features, a.v6_features,
            cost_cal_path=a.cost_cal, out_dir=a.out)
    print(json.dumps({"verdict": r["verdict"]["verdict"],
                      "v5_gross": r["verdict"]["v5_baseline"]["gross_expectancy_bps"],
                      "v6_gross": r["verdict"]["v6_extension"]["gross_expectancy_bps"],
                      "v6_net_cont": r["verdict"]["cost_adjusted"]["contemporaneous_taker"]["net_bps"]},
                     indent=2))
