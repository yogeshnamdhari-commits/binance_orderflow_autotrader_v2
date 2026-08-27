#!/usr/bin/env python3
"""
Re-run V5 OOS validation with corrected execution cost.
Read-only: does not modify any production file.
"""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

PROJECT = Path("/Users/targetmobile/Downloads/binance_orderflow_autotrader_v2")
DATA_RESEARCH = PROJECT / "data" / "research"
DATA_HIST_RESEARCH = PROJECT / "data" / "hist" / "research"

# ---------------------------------------------------------------------------
# Cost model (replicated from app/v3_cost.py, read-only)
# ---------------------------------------------------------------------------
DEFAULT_CAL_PATH = DATA_HIST_RESEARCH / "execution_calibration.json"
DEFAULT_NOTIONAL_USD = 1000.0
SAFETY_MARGIN_BPS = 0.5
IMPACT_ALLOWANCE_BPS = 0.10
LATENCY_COST_BPS = 0.05
NON_FILL_REPRICE_COST_BPS = 0.50
P_FILL_DEFAULT = 0.70
PRIMARY_HORIZON = 500


def load_cal(cal_path=DEFAULT_CAL_PATH):
    return json.load(open(cal_path))


def _adjacent(arr, key):
    ts = sorted(int(k) for k in arr)
    best = ts[0] if ts else None
    for t in ts:
        if t >= key:
            best = t
            break
        best = t
    return best


def taker_cost_bps(cal, notional_usd=DEFAULT_NOTIONAL_USD):
    band = _adjacent(cal.get("effective_taker_roundtrip", {}), notional_usd)
    if band is None:
        return round(2.5 + IMPACT_ALLOWANCE_BPS + LATENCY_COST_BPS, 6)
    rt = cal["effective_taker_roundtrip"][str(band)]["p90_bps"]
    return round(float(rt) + IMPACT_ALLOWANCE_BPS + LATENCY_COST_BPS, 6)


def maker_components(cal):
    oos = cal.get("oos_fill", {})
    drags, pfills = [], []
    for cell in oos.values():
        g = cell.get("gross_unconditional_bps")
        e = cell.get("e_fill_return_bps")
        if g is not None and e is not None:
            drags.append(g - e)
        if cell.get("p_fill_same_tick") is not None:
            pfills.append(cell["p_fill_same_tick"])
    drag = sorted(drags)[len(drags) // 2] if drags else 0.50
    p_fill = sorted(pfills)[len(pfills) // 2] if pfills else P_FILL_DEFAULT
    return {"adverse_selection_bps": round(drag, 4), "p_fill": round(p_fill, 4),
            "n_cells": len(oos)}


def maker_cost_bps(cal):
    comp = maker_components(cal)
    fee = float(cal.get("maker_fee_rt_bps", 2.0))
    reprice = NON_FILL_REPRICE_COST_BPS * (1.0 - comp["p_fill"])
    total = fee + comp["adverse_selection_bps"] + reprice + LATENCY_COST_BPS
    return round(total, 6), comp


def cost_model(cal, notional_usd=DEFAULT_NOTIONAL_USD, margin_bps=SAFETY_MARGIN_BPS):
    tak, mak_comp = taker_cost_bps(cal, notional_usd), maker_components(cal)
    mak, _ = maker_cost_bps(cal)
    return {
        "notional_usd": float(notional_usd),
        "safety_margin_bps": margin_bps,
        "taker": {"total_bps": tak, "margin_bps": margin_bps,
                  "gate_bps": tak + margin_bps,
                  "components": {
                      "basis": "effective_taker_roundtrip.p90 + impact + latency",
                      "spread_bps": cal.get("spread", {}).get("p90_bps"),
                      "slippage_bps": cal.get("slippage_by_notional", {})
                                       .get(str(int(notional_usd)), {})
                                       .get("buy_p90_bps")}},
        "maker": {"total_bps": mak, "margin_bps": margin_bps,
                  "gate_bps": mak + margin_bps,
                  "components": {"adverse_selection_bps":
                                     mak_comp["adverse_selection_bps"],
                                 "p_fill": mak_comp["p_fill"],
                                 "maker_fee_rt_bps":
                                     cal.get("maker_fee_rt_bps", 2.0)}},
    }


# ---------------------------------------------------------------------------
# V5 model loading (replicated from app/v5_model.py)
# ---------------------------------------------------------------------------
def load_model(path):
    return json.load(open(path))


def predict(model_d, df, horizon_ms=PRIMARY_HORIZON):
    d = model_d[str(horizon_ms)]
    X = df[model_d["features"]] if hasattr(df, "columns") else df
    Z = (X.to_numpy(float) - np.array(d["mean"])) / np.array(d["std"])
    Zt = np.where(np.isfinite(Z), Z, 0.0)
    return d["intercept"] + Zt @ np.array(d["coef"])


def chrono_split_masks(df, split_fractions=(0.70, 0.15, 0.15)):
    ts = df["ts_ms"].to_numpy(dtype=np.int64)
    lo, mid, hi = split_fractions
    cut1 = np.quantile(ts, lo)
    cut2 = np.quantile(ts, lo + mid)
    return ({'name': 'train', 'mask': ts <= cut1},
            {'name': 'validation', 'mask': (ts > cut1) & (ts <= cut2)},
            {'name': 'oos', 'mask': ts > cut2})


# ---------------------------------------------------------------------------
# V5 labels (same as V3)
# ---------------------------------------------------------------------------
def add_labels(df, horizons=(250, 500, 1000)):
    df = df.sort_values("ts_ms").reset_index(drop=True)
    ts = df["ts_ms"].to_numpy(dtype=np.int64)
    mid = df["mid"].to_numpy(dtype=float)
    microb = df["microb_price"].to_numpy(dtype=float)
    n = len(df)
    for h in horizons:
        ptr = np.searchsorted(ts, ts + h, side="left")
        valid = ptr < n
        r = np.full(n, np.nan)
        r[valid] = (mid[ptr[valid]] - mid[valid]) / mid[valid] * 1e4
        df["r_%d" % h] = r
        m = np.full(n, np.nan)
        mb_ok = valid & np.isfinite(microb)
        m[mb_ok] = (microb[ptr[mb_ok]] - microb[mb_ok]) / microb[mb_ok] * 1e4
        df["m_%d" % h] = m
    return df


# ---------------------------------------------------------------------------
# Non-overlap keep (replicated from app/v5_validation.py)
# ---------------------------------------------------------------------------
def non_overlap_keep(df, horizon_ms=PRIMARY_HORIZON):
    keep, last = [], None
    for _, r in df.iterrows():
        if last is None or r["ts_ms"] - last >= horizon_ms:
            keep.append(r.name)
            last = r["ts_ms"]
    return df.loc[keep]


def _maxdd(trail):
    if len(trail) == 0:
        return 0.0
    s, peak, mdd = 0.0, 0.0, 0.0
    for x in trail:
        s += x
        peak = max(peak, s)
        mdd = max(mdd, peak - s)
    return mdd


# ---------------------------------------------------------------------------
# V5 scoreboard
# ---------------------------------------------------------------------------
def scoreboard(oos, pred, gate, horizon_ms=PRIMARY_HORIZON):
    y = oos["r_%d" % horizon_ms].to_numpy(float)
    states = np.where(pred > gate, "LONG", np.where(pred < -gate, "SHORT", "NO_TRADE"))
    gross = np.where(np.sign(pred) == 0, 0.0, np.sign(pred))
    gross_move = gross * y
    executed = states != "NO_TRADE"
    net_exe = (np.where(executed, 0.0, 0.0) +
               np.where(executed, np.sign(pred) * y - gate, 0.0))
    
    sb = {
        "horizon_ms": horizon_ms, "gate_bps": gate, "oos_rows": int(len(oos)),
        "executed_rows": int(executed.sum()), "no_trade_rows": int((~executed).sum()),
        "gross_dir_n": int((pred != 0).sum()),
        "gross_expectancy_bps": float(np.nanmean(gross_move)),
        "gross_std_bps": float(np.nanstd(gross_move)),
        "gated_expectancy_bps": float(net_exe[executed].mean())
        if executed.any() else 0.0,
        "gated_std_bps": float(net_exe[executed].std()) if executed.any() else 0.0,
        "per_direction": {},
        "per_session": {},
        "per_regime": {},
    }
    
    for st in ("LONG", "SHORT"):
        m = states == st
        sb["per_direction"][st] = {
            "n": int(m.sum()),
            "realized_move_bps": float(np.nanmean(y[m])) if m.any() else 0.0,
            "net_bps": float(np.nanmean(np.sign(pred[m]) * y[m] - gate)) if m.any() else 0.0,
            "win_rate": float(np.nanmean((np.sign(pred[m]) * y[m] - gate) > 0)) if m.any() else 0.0,
        }
    
    sess = {}
    for s in oos["session"].unique():
        m = oos["session"] == s
        em = m.to_numpy() & executed
        sess[s] = {"rows": int(m.sum()), "executed_rows": int(em.sum()),
                   "gross_bps": float(np.nanmean(gross_move[m.to_numpy()])),
                   "net_bps": float(np.nanmean(net_exe[em])) if em.any() else 0.0}
    sb["per_session"] = sess
    tot_exe = max(1, int(executed.sum()))
    sb["largest_session_share"] = float(max(v["executed_rows"]
                                            for v in sess.values()) / tot_exe)
    
    # Regime breakdown
    for regime in oos["regime"].unique():
        m_regime = oos["regime"] == regime
        em = m_regime.to_numpy() & executed
        if em.any():
            sb["per_regime"][regime] = {
                "executed_rows": int(em.sum()),
                "gross_bps": float(np.nanmean(gross_move[m_regime.to_numpy()])),
                "net_bps": float(np.nanmean(net_exe[em])),
            }
    
    # Risk statistics on non-overlapping executed trail
    nomask = executed
    ex = oos.loc[nomask]
    k = non_overlap_keep(ex.reset_index(drop=True), horizon_ms=horizon_ms)
    trail = (np.sign(pred[nomask]) * y[nomask] - gate)[k.index.to_numpy()]
    sb["pf"] = (float(trail[trail > 0].sum() / -trail[trail < 0].sum())
                if (trail[trail < 0].sum()) != 0 else
                (float("inf") if (trail[trail > 0].sum()) > 0 else 0.0))
    sb["sharpe"] = float(trail.mean() / trail.std()) if len(trail) > 1 and trail.std() > 0 else 0.0
    sb["max_drawdown_bps"] = float(_maxdd(trail))
    sb["net_trail_n"] = int(len(trail))
    
    # Statistical significance for gated expectancy
    if executed.any() and len(net_exe[executed]) > 1:
        net_exec = net_exe[executed]
        sem = net_exec.std() / math.sqrt(len(net_exec))
        ci = stats.t.interval(0.95, len(net_exec)-1, loc=net_exec.mean(), scale=sem)
        t_stat = net_exec.mean() / sem if sem > 0 else 0.0
        p_val = 2.0 * stats.t.sf(abs(t_stat), len(net_exec)-1)
        sb["gated_ci_95_low"] = round(float(ci[0]), 6)
        sb["gated_ci_95_high"] = round(float(ci[1]), 6)
        sb["gated_t_stat"] = round(float(t_stat), 6)
        sb["gated_p_value"] = round(float(p_val), 6)
    else:
        sb["gated_ci_95_low"] = 0.0
        sb["gated_ci_95_high"] = 0.0
        sb["gated_t_stat"] = 0.0
        sb["gated_p_value"] = 1.0
    
    return sb


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def validate(model_path, cost_path, feature_path, out_path, horizon_ms=PRIMARY_HORIZON):
    model = load_model(model_path)
    cal = load_cal(cost_path)
    cost = cost_model(cal)
    gate = float(cost["taker"]["gate_bps"])
    
    df = pd.read_parquet(feature_path)
    df = add_labels(df)
    splits = chrono_split_masks(df)
    oos = df.loc[splits[2]["mask"]].reset_index(drop=True)
    
    pred = predict(model, oos, horizon_ms)
    
    sb = scoreboard(oos, pred, gate, horizon_ms)
    
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": str(model_path),
        "cost_calibration": str(cost_path),
        "style": "taker",
        "notional_usd": 1000.0,
        "horizon_ms": horizon_ms,
        "gate_bps": gate,
        "cost_model": cost,
        "split_fractions": [0.7, 0.15, 0.15],
        "days": {s["name"]: {"lo_ms": int(df.loc[s["mask"], "ts_ms"].min()),
                             "hi_ms": int(df.loc[s["mask"], "ts_ms"].max()),
                             "rows": int(s["mask"].sum())} for s in splits},
        "scoreboard": sb,
        "verdict": "INSUFFICIENT",
    }
    
    # Verdict logic
    long_n = sb["per_direction"]["LONG"]["n"]
    short_n = sb["per_direction"]["SHORT"]["n"]
    net = sb["gated_expectancy_bps"]
    conclude = long_n >= 200 and short_n >= 200
    report["verdict"] = ("STOP" if (conclude and net <= 0)
                         else ("PASS" if conclude and net > 0
                               else "INSUFFICIENT"))
    
    out_path = Path(out_path)
    out_path.write_text(json.dumps(report, indent=1))
    return report


if __name__ == "__main__":
    model_path = DATA_RESEARCH / "v5_model.json"
    cost_path = DATA_HIST_RESEARCH / "execution_calibration.json"
    feature_path = DATA_RESEARCH / "v5_features.parquet"
    out_path = DATA_RESEARCH / "V5_OOS_CORRECTED.json"
    
    r = validate(model_path, cost_path, feature_path, out_path)
    sb = r["scoreboard"]
    print(json.dumps({
        "verdict": r["verdict"],
        "gate_bps": r["gate_bps"],
        "gross_expectancy_bps": sb["gross_expectancy_bps"],
        "gated_expectancy_bps": sb["gated_expectancy_bps"],
        "gated_ci_95": [sb["gated_ci_95_low"], sb["gated_ci_95_high"]],
        "gated_t_stat": sb["gated_t_stat"],
        "gated_p_value": sb["gated_p_value"],
        "executed_rows": sb["executed_rows"],
        "no_trade_rows": sb["no_trade_rows"],
        "long_n": sb["per_direction"]["LONG"]["n"],
        "short_n": sb["per_direction"]["SHORT"]["n"],
        "pf": sb["pf"],
        "sharpe": sb["sharpe"],
        "max_drawdown_bps": sb["max_drawdown_bps"],
        "regimes": sb["per_regime"],
    }, indent=1))
