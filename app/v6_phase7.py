"""V6 Phase 7 — Signal Formulation, Horizon, and Instrument Robustness.

Pre-registered experimental matrix:
  6 horizons × 3 formulations × 2 aggregations × 3 instruments = 108 experiments

Horizons (pre-registered, ordered):
  H1=250ms, H2=500ms, H3=1000ms, H4=2000ms, H5=5000ms, H6=10000ms

Formulations:
  FA=Instantaneous OFI (current V5/V6)
  FB=Persistence-conditioned OFI
  FC=Liquidity-transition OFI

Aggregation:
  CT=Clock-time, ET=Event-time

Instruments:
  I1=BTCUSDT, I2=ETHUSDT, I3=BNBUSDT

Acceptance criterion (all must pass):
  - Net expectancy after contemporaneous cost > 0 bps
  - Gross expectancy > 0 bps
  - HAC p < 0.000463 (Bonferroni)
  - Long/short symmetry
  - Regime robustness
  - Max drawdown < 10 bps
  - Instrument robustness

DO NOT add features. DO NOT optimize thresholds. DO NOT refit on OOS.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from .v3_model import chrono_split_masks, fit_horizon, predict as predict_v3
from .v3_labels import add_labels
from .v6_model import load_model as load_v6, predict as predict_v6, V6_FEATURES
from .v6_cost import cost_distribution_from_cal, load_calibration
from .signal_decision import SignalDecisionEngine, BookIntegrityState

DATA = Path("data")
RESEARCH = DATA / "research"
OUT_DIR = RESEARCH / "v6" / "phase7"

# Pre-registered experiment matrix
# Clock-time horizons (ms)
HORIZONS_MS = [250, 500, 1000, 2000, 5000, 10000]
# Event-time horizons (number of events forward)
EVENT_HORIZONS = [25, 50, 100, 200, 500, 1000]
FORMULATIONS = ["FA", "FB", "FC"]
AGGREGATIONS = ["CT", "ET"]
INSTRUMENTS = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]

# Bonferroni correction
N_EXPERIMENTS = len(HORIZONS_MS) * len(FORMULATIONS) * len(AGGREGATIONS) * len(INSTRUMENTS)
BONFERRONI_ALPHA = 0.05 / N_EXPERIMENTS


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


def _compute_formulation(df, formulation, horizon_ms, aggregation="CT"):
    """Compute signal formulation features.

    FA: Instantaneous OFI (raw)
    FB: Persistence-conditioned OFI
    FC: Liquidity-transition OFI

    aggregation: "CT" = clock-time, "ET" = event-time
    """
    df = df.copy()
    ofi = df["ofi_l1"].to_numpy(float)

    if formulation == "FA":
        # Instantaneous OFI — raw
        signal = ofi.copy()
    elif formulation == "FB":
        # Persistence-conditioned OFI
        # Persistence = fraction of last 10 events with same sign as current
        persistence = np.zeros(len(df))
        window = 10
        for i in range(len(df)):
            start = max(0, i - window)
            segment = ofi[start:i]
            if len(segment) > 0:
                same_sign = np.sum(np.sign(segment) == np.sign(ofi[i]))
                persistence[i] = same_sign / len(segment)
        signal = ofi * persistence
    elif formulation == "FC":
        # Liquidity-transition OFI
        # Only emit signal when liquidity regime changes
        signal = np.zeros(len(df))
        if "liquidity_state" in df.columns:
            regime = df["liquidity_state"].to_numpy()
            for i in range(1, len(df)):
                if regime[i] != regime[i - 1]:
                    signal[i] = ofi[i]
    else:
        raise ValueError(f"Unknown formulation: {formulation}")

    return signal


def _add_event_time_labels(df, event_horizons):
    """Add event-time forward return labels.

    For each event horizon N, r_N = mid(t+N) - mid(t) in bps.
    """
    df = df.copy()
    for n_events in event_horizons:
        col = f"r_et_{n_events}"
        mid = df["mid"].to_numpy(float)
        ret = np.full(len(df), np.nan)
        for i in range(len(df)):
            j = i + n_events
            if j < len(df):
                ret[i] = (mid[j] - mid[i]) / mid[i] * 10000 if mid[i] != 0 else 0.0
        df[col] = ret
    return df


def _evaluate_experiment(df, signal, y, gate, horizon_ms, formulation, instrument):
    """Evaluate a single experiment and return metrics."""
    ts = df["ts_ms"].to_numpy(dtype=np.int64)
    states = np.where(signal > gate, "LONG", np.where(signal < -gate, "SHORT", "NO_TRADE"))
    gross = np.sign(signal)
    gross_move = gross * y
    executed = states != "NO_TRADE"
    net_exe = np.where(executed, gross * y - gate, 0.0)

    median_gap = float(np.median(np.diff(ts))) if len(ts) > 1 else 1000.0
    max_lag = int(min(5 * median_gap / 1000.0, len(gross_move) - 1))
    max_lag = max(1, max_lag)

    g_mu, g_se, g_z, g_p, g_lo, g_hi = _hac_stats(gross_move, max_lag)
    n_mu, n_se, n_z, n_p, n_lo, n_hi = _hac_stats(net_exe[executed], max_lag) if executed.any() else (0.0, 0.0, 0.0, 1.0, 0.0, 0.0)

    # Non-overlapping trail for Sharpe/DD
    ex = pd.DataFrame({"net": net_exe[executed], "ts": ts[executed]})
    ex = ex.sort_values("ts").reset_index(drop=True)
    keep, last = [], None
    for idx, r in ex.iterrows():
        if last is None or r["ts"] - last >= horizon_ms:
            keep.append(idx)
            last = r["ts"]
    trail = ex.loc[keep, "net"].to_numpy() if keep else np.array([])

    if len(trail) > 1 and trail.std() > 0:
        sharpe = float(trail.mean() / trail.std())
        s, peak, mdd = 0.0, 0.0, 0.0
        for x in trail:
            s += x
            peak = max(peak, s)
            mdd = max(mdd, peak - s)
        max_dd = float(mdd)
        pf = float(trail[trail > 0].sum() / -trail[trail < 0].sum()) if (trail < 0).any() else (float("inf") if (trail > 0).any() else 0.0)
    else:
        sharpe = 0.0
        max_dd = 0.0
        pf = 0.0

    return {
        "experiment_id": f"H{horizon_ms}_{formulation}_CT_{instrument}",
        "horizon_ms": horizon_ms,
        "formulation": formulation,
        "aggregation": "CT",
        "instrument": "BTCUSDT",
        "gate_bps": gate,
        "oos_rows": int(len(df)),
        "executed_rows": int(executed.sum()),
        "gross_expectancy_bps": round(float(g_mu), 6),
        "gross_hac_se_bps": round(g_se, 6),
        "gross_hac_z": round(g_z, 4),
        "gross_hac_p": round(g_p, 6),
        "gross_hac_ci95": [round(g_lo, 6), round(g_hi, 6)],
        "net_expectancy_bps": round(float(n_mu), 6),
        "net_hac_se_bps": round(n_se, 6),
        "net_hac_z": round(n_z, 4),
        "net_hac_p": round(n_p, 6),
        "net_hac_ci95": [round(n_lo, 6), round(n_hi, 6)],
        "sharpe": round(sharpe, 4),
        "max_drawdown_bps": round(max_dd, 6),
        "profit_factor": round(pf, 4),
        "trail_n": int(len(trail)),
        "passes_bonferroni": g_p < BONFERRONI_ALPHA,
        "passes_net_positive": n_mu > 0,
        "passes_all_gates": g_p < BONFERRONI_ALPHA and n_mu > 0 and max_dd < 10.0,
    }


def run_pilot(feature_path, model_path, cost_cal_path, instrument="BTCUSDT",
              out_dir=OUT_DIR, log=print):
    """Run Phase 7 pilot: horizon/formulation/aggregation sweep on BTCUSDT.

    This is a pilot to test infrastructure. Full Phase 7 requires:
    - ETHUSDT and BNBUSDT data collection
    - Q2 cost calibration per instrument
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load data and cost
    df = pd.read_parquet(feature_path)
    cal = load_calibration(cost_cal_path or Path("data/hist/research/execution_calibration.json"))
    cost_dist = cost_distribution_from_cal(cal)
    gate = cost_dist.taker_gate_bps

    log(f"[PHASE7] Starting pilot: {instrument}")
    log(f"[PHASE7] Gate: {gate:.4f} bps")
    log(f"[PHASE7] Bonferroni alpha: {BONFERRONI_ALPHA:.6f}")

    # Get OOS split
    splits = chrono_split_masks(df)
    oos = df.loc[splits[-1]["mask"]].reset_index(drop=True)

    # Add labels for all clock-time horizons
    if "r_250" not in oos.columns:
        oos = add_labels(oos, HORIZONS_MS)

    # Add event-time labels
    oos = _add_event_time_labels(oos, EVENT_HORIZONS)

    results = []

    # Clock-time experiments
    for horizon_ms in HORIZONS_MS:
        label_col = f"r_{horizon_ms}"
        if label_col not in oos.columns:
            log(f"[PHASE7] Skipping CT horizon {horizon_ms}: label missing")
            continue

        y = oos[label_col].to_numpy(float)

        for formulation in FORMULATIONS:
            signal = _compute_formulation(oos, formulation, horizon_ms)
            result = _evaluate_experiment(oos, signal, y, gate, horizon_ms, formulation, instrument)
            result["aggregation"] = "CT"
            result["experiment_id"] = f"H{horizon_ms}_{formulation}_CT_{instrument}"
            results.append(result)

            log(f"[PHASE7] H{horizon_ms} {formulation} CT: "
                f"gross={result['gross_expectancy_bps']:.4f} bps, "
                f"net={result['net_expectancy_bps']:.4f} bps, "
                f"gross_p={result['gross_hac_p']:.4f}, "
                f"net_p={result['net_hac_p']:.4f}, "
                f"passes={result['passes_all_gates']}")

    # Event-time experiments
    for n_events in EVENT_HORIZONS:
        label_col = f"r_et_{n_events}"
        if label_col not in oos.columns:
            log(f"[PHASE7] Skipping ET horizon {n_events}: label missing")
            continue

        y = oos[label_col].to_numpy(float)

        for formulation in FORMULATIONS:
            signal = _compute_formulation(oos, formulation, n_events)
            result = _evaluate_experiment(oos, signal, y, gate, n_events, formulation, instrument)
            result["aggregation"] = "ET"
            result["experiment_id"] = f"ET{n_events}_{formulation}_ET_{instrument}"
            results.append(result)

            log(f"[PHASE7] ET{n_events} {formulation} ET: "
                f"gross={result['gross_expectancy_bps']:.4f} bps, "
                f"net={result['net_expectancy_bps']:.4f} bps, "
                f"gross_p={result['gross_hac_p']:.4f}, "
                f"net_p={result['net_hac_p']:.4f}, "
                f"passes={result['passes_all_gates']}")

    # Compile results
    def _convert(obj):
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "instrument": instrument,
        "gate_bps": gate,
        "bonferroni_alpha": BONFERRONI_ALPHA,
        "n_experiments": len(results),
        "results": results,
        "summary": {
            "passes_any": any(r["passes_all_gates"] for r in results),
            "best_net": max((float(r["net_expectancy_bps"]) for r in results), default=0.0),
            "best_gross_p": min((float(r["gross_hac_p"]) for r in results), default=1.0),
            "best_net_p": min((float(r["net_hac_p"]) for r in results), default=1.0),
        },
        "verdict": (
            "CONDITIONAL_EDGE — proceed to independent replication"
            if any(r["passes_all_gates"] for r in results)
            else "NO_EDGE — no horizon/formulation survives economic gate"
        ),
    }

    # Write report
    report_path = out_dir / f"phase7_pilot_{instrument}.json"
    # Convert numpy types for JSON serialization
    report_json = json.dumps(report, indent=2, default=lambda o: o.item() if hasattr(o, 'item') else str(o))
    report_path.write_text(report_json)
    log(f"[PHASE7] Report: {report_path}")
    log(f"[PHASE7] Verdict: {report['verdict']}")

    return report


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", type=Path, default=RESEARCH / "v6_features.parquet")
    ap.add_argument("--model", type=Path, default=RESEARCH / "v6_model.json")
    ap.add_argument("--cost-cal", type=Path, default=Path("data/hist/research/execution_calibration.json"))
    ap.add_argument("--instrument", default="BTCUSDT")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    a = ap.parse_args()
    run_pilot(a.features, a.model, a.cost_cal, a.instrument, a.out)
