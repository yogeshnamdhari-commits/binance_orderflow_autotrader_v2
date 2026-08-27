#!/usr/bin/env python3
"""
TIER A — Long-horizon re-validation of ORDERFLOW_BASELINE_V5
Frozen 500 ms signal direction evaluated at longer holding horizons.
Zero refit. Zero parameter change. Zero feature change.
No external deps beyond numpy/pandas/stdlib.
"""
import json, math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path("/Users/targetmobile/Downloads/binance_orderflow_autotrader_v2")
DATA_RESEARCH = PROJECT / "data" / "research"
DATA_HIST_RESEARCH = PROJECT / "data" / "hist" / "research"

PREREGISTERED_HORIZONS = (2000, 5000, 10000, 30000)
BASE_HORIZON_MS = 500
GATE_BPS = 4.6658
MAX_LAG_FACTOR = 5
_N_SQRT2 = math.sqrt(2.0)


def normal_cdf(x):
    return 0.5 * (1.0 + math.erf(x / _N_SQRT2))


def normal_sf(x):
    return 1.0 - normal_cdf(x)


def load_model(path):
    return json.load(open(path))


def predict(model_d, X_df):
    d = model_d[str(BASE_HORIZON_MS)]
    X = X_df[model_d["features"]].to_numpy(float)
    mu = np.array(d["mean"])
    sd = np.array(d["std"])
    Z = (X - mu) / sd
    Zt = np.where(np.isfinite(Z), Z, 0.0)
    return d["intercept"] + Zt @ np.array(d["coef"])


def add_labels(df, horizons):
    df = df.sort_values("ts_ms").reset_index(drop=True)
    ts = df["ts_ms"].to_numpy(dtype=np.int64)
    mid = df["mid"].to_numpy(dtype=float)
    n = len(df)
    for h in horizons:
        ptr = np.searchsorted(ts, ts + h, side="left")
        valid = ptr < n
        r = np.full(n, np.nan)
        r[valid] = (mid[ptr[valid]] - mid[valid]) / mid[valid] * 1e4
        df[f"r_{h}"] = r
    return df


def chrono_split_masks(df, split_fractions=(0.70, 0.15, 0.15)):
    ts = df["ts_ms"].to_numpy(dtype=np.int64)
    lo, mid, hi = split_fractions
    cut1 = np.quantile(ts, lo)
    cut2 = np.quantile(ts, lo + mid)
    return ({'name': 'train', 'mask': ts <= cut1},
            {'name': 'validation', 'mask': (ts > cut1) & (ts <= cut2)},
            {'name': 'oos', 'mask': ts > cut2})


def newey_west_se(x, max_lag):
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


def hac_stats(x, max_lag):
    x = np.asarray(x, dtype=float)
    mu = float(np.nanmean(x))
    se = newey_west_se(x, max_lag)
    z = mu / se if se > 0 else 0.0
    p = 2.0 * normal_sf(abs(z))
    ci_lo = mu - 1.96 * se
    ci_hi = mu + 1.96 * se
    return mu, se, z, p, ci_lo, ci_hi


def analyze_horizon(oos, pred, horizon_ms, max_lag):
    r = oos[f"r_{horizon_ms}"].to_numpy(dtype=float)
    valid = np.isfinite(r)
    n = int(valid.sum())
    if n == 0:
        return {"horizon_ms": horizon_ms, "n": 0, "note": "No valid labels"}

    # Filtered arrays for valid labels only
    r_v = r[valid]
    pred_v = pred[valid]
    signal = np.sign(pred_v)

    # ALL
    gross = signal * r_v
    g_mean, g_se, g_z, g_p, g_lo, g_hi = hac_stats(gross, max_lag)
    net_mean = g_mean - GATE_BPS
    se_classical = float(np.nanstd(gross) / math.sqrt(n)) if n > 0 else 0.0
    pct_pos = float(np.nanmean(gross > 0)) if n > 0 else 0.0

    # LONG
    long_mask = pred_v > 0
    long_n = int(long_mask.sum())
    long_gross = r_v[long_mask] if long_n > 0 else np.array([], dtype=float)
    long_gross_mean = float(np.nanmean(long_gross)) if long_n > 0 else 0.0
    long_net_mean = long_gross_mean - GATE_BPS

    # SHORT
    short_mask = pred_v < 0
    short_n = int(short_mask.sum())
    short_gross = (-r_v[short_mask]) if short_n > 0 else np.array([], dtype=float)
    short_gross_mean = float(np.nanmean(short_gross)) if short_n > 0 else 0.0
    short_net_mean = short_gross_mean - GATE_BPS

    # REGIME (use full-length regime mask, then intersect with valid)
    regimes = {}
    for regime in sorted(oos["regime"].dropna().unique()):
        regime_full = (oos["regime"] == regime).to_numpy()
        m = regime_full & valid
        if not m.any():
            continue
        r_reg = r[m]
        p_reg = pred[m]
        gross_reg = np.sign(p_reg) * r_reg
        regimes[str(regime)] = {
            "n": int(m.sum()),
            "gross_mean_bps": round(float(np.nanmean(gross_reg)), 6),
            "net_mean_bps_taker": round(float(np.nanmean(gross_reg) - GATE_BPS), 6),
        }

    return {
        "horizon_ms": horizon_ms,
        "n": n,
        "long_n": long_n,
        "short_n": short_n,
        "gross_mean_bps": round(g_mean, 6),
        "gross_median_bps": round(float(np.nanmedian(gross)), 6),
        "gross_std_bps": round(float(np.nanstd(gross)), 6),
        "se_classical_bps": round(se_classical, 6),
        "se_hac_bps": round(g_se, 6),
        "ci_95_hac_low": round(g_lo, 6),
        "ci_95_hac_high": round(g_hi, 6),
        "z_hac": round(g_z, 6),
        "p_value_hac": round(g_p, 6),
        "net_mean_bps_taker": round(net_mean, 6),
        "long_gross_mean_bps": round(long_gross_mean, 6),
        "long_net_mean_bps_taker": round(long_net_mean, 6),
        "short_gross_mean_bps": round(short_gross_mean, 6),
        "short_net_mean_bps_taker": round(short_net_mean, 6),
        "pct_positive": round(pct_pos, 6),
        "regimes": regimes,
        "hac_max_lag": int(max_lag),
    }


def main():
    model_path = DATA_RESEARCH / "v3_model.json"
    feature_path = DATA_RESEARCH / "v3_features.parquet"

    model = load_model(model_path)
    df = pd.read_parquet(feature_path)
    splits = chrono_split_masks(df)
    oos = df.loc[splits[2]["mask"]].reset_index(drop=True)

    pred = predict(model, oos)

    ts_oos = oos["ts_ms"].to_numpy(dtype=np.int64)
    median_gap = float(np.median(np.diff(ts_oos)))
    max_lag = int(min(MAX_LAG_FACTOR * median_gap, len(oos) - 1))

    horizons_results = {}
    for h in PREREGISTERED_HORIZONS:
        if f"r_{h}" not in oos.columns:
            tmp = oos[["ts_ms", "mid", "regime"]].copy()
            ptr = np.searchsorted(ts_oos, ts_oos + h, side="left")
            valid = ptr < len(ts_oos)
            mid = oos["mid"].to_numpy(dtype=float)
            r = np.full(len(oos), np.nan)
            r[valid] = (mid[ptr[valid]] - mid[valid]) / mid[valid] * 1e4
            oos[f"r_{h}"] = r
        horizons_results[str(h)] = analyze_horizon(oos, pred, h, max_lag)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline": "ORDERFLOW_BASELINE_V5 — NO LIVE TRADING",
        "protocol": (
            "Tier A: zero-refit evaluation of frozen 500 ms signal direction "
            "at longer holding horizons. No model, feature, or parameter changes."
        ),
        "signal_definition": (
            "sign(pred_500ms) from v3_model.json applied to OOS. "
            "gross = sign(pred_500ms) * r_h."
        ),
        "preregistered_horizons_ms": list(PREREGISTERED_HORIZONS),
        "gate_bps": GATE_BPS,
        "gate_note": (
            "Historical non-contemporaneous taker round-trip cost (4.6658 bps). "
            "Derived from execution_calibration.json collected ~42 h BEFORE this OOS "
            "window (2026-08-17 18:16 UTC vs OOS 2026-08-19 01:20 UTC). "
            "Indicative reference ONLY. Does not establish contemporaneous profitability."
        ),
        "oos": {
            "start_ts_ms": int(oos["ts_ms"].min()),
            "end_ts_ms": int(oos["ts_ms"].max()),
            "span_ms": int(oos["ts_ms"].max() - oos["ts_ms"].min()),
            "rows": int(len(oos)),
            "median_event_gap_ms": median_gap,
            "hac_max_lag": int(max_lag),
        },
        "horizons": horizons_results,
    }

    out_path = DATA_RESEARCH / "FORENSIC_VALIDATION_PHASE_2_TIER_A.json"
    out_path.write_text(json.dumps(report, indent=1))

    print("=" * 120)
    print("ORDERFLOW_BASELINE_V5 — TIER A: Zero-refit longer-horizon validation")
    print("=" * 120)
    print(f"Signal: sign of frozen 500 ms prediction (no refit, no parameter change)")
    print(f"Cost gate: {GATE_BPS} bps taker round-trip (HISTORICAL / NON-CONTEMPORANEOUS)")
    print(f"OOS rows: {len(oos)}  |  Span: {oos['ts_ms'].max()-oos['ts_ms'].min()} ms  |  Median gap: {median_gap:.1f} ms")
    print(f"HAC max lag: {max_lag}")
    print()
    print(f"{'Horizon':>10} | {'N':>6} | {'Gross bps':>10} | {'Cost bps':>10} | {'Net bps':>10} | {'95% CI (HAC)':>22} | {'HAC p':>10} | {'Verdict':>12}")
    print("-" * 120)

    for h in PREREGISTERED_HORIZONS:
        res = horizons_results[str(h)]
        if res.get("n", 0) == 0:
            print(f"{h:>10} | {'N/A':>6} | {'N/A':>10} | {'N/A':>10} | {'N/A':>10} | {'N/A':>22} | {'N/A':>10} | {'INSUFFICIENT':>12}")
            continue
        ci = f"[{res['ci_95_hac_low']:.4f}, {res['ci_95_hac_high']:.4f}]"
        verdict = "STOP" if res["net_mean_bps_taker"] <= 0 else "PASS"
        print(f"{h:>10} | {res['n']:>6} | {res['gross_mean_bps']:>10.4f} | {GATE_BPS:>10.4f} | {res['net_mean_bps_taker']:>10.4f} | {ci:>22} | {res['p_value_hac']:>10.6f} | {verdict:>12}")

    print()
    print("Detailed JSON:", out_path)
    print()
    print("NOTE: Overlapping returns at longer horizons mean effective sample size < raw N.")
    print("      HAC SE is the primary inferential statistic; classical SE is for reference only.")


if __name__ == "__main__":
    main()
