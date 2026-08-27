#!/usr/bin/env python3
"""
Re-run V3 OOS validation with corrected execution cost.
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
# V3 model loading (replicated from app/v3_model.py)
# ---------------------------------------------------------------------------
def load_model(path):
    return json.load(open(path))


def predict(model_d, df, horizon_ms):
    d = model_d[str(horizon_ms)]
    X = df[model_d["features"]].to_numpy(float) if hasattr(df, "columns") else df
    mu = np.array(d["mean"])
    sd = np.array(d["std"])
    Z = (X - mu) / sd
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
# V3 labels (replicated from app/v3_labels.py)
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
# Scoring
# ---------------------------------------------------------------------------
def _score(label, pred, gate_bps, direction):
    pred = np.asarray(pred, dtype=float)
    label = np.asarray(label, dtype=float)
    sel = (pred > 0) & np.isfinite(label) if direction == "long" \
        else (pred < 0) & np.isfinite(label)
    if int(sel.sum()) == 0:
        return {"direction": direction, "n": 0}
    y = label[sel]
    gross = y if direction == "long" else -y
    net = gross - gate_bps
    wins = net[net > 0]
    losses = -net[net <= 0]
    pf = float(wins.sum() / losses.sum()) if losses.sum() > 0 \
        else (float("inf") if wins.sum() > 0 else 0.0)
    return {"direction": direction, "n": int(sel.sum()),
            "gross_mean_bps": round(float(gross.mean()), 6),
            "net_mean_bps": round(float(net.mean()), 6),
            "net_median_bps": round(float(np.median(net)), 6),
            "hit_rate": round(float((net > 0).mean()), 6),
            "profit_factor": pf}


def _maxdd(trail):
    if len(trail) == 0:
        return 0.0
    s, peak, mdd = 0.0, 0.0, 0.0
    for x in trail:
        s += x
        peak = max(peak, s)
        mdd = max(mdd, peak - s)
    return mdd


def validate(model_path, cost_path, feature_path, out_path, horizon_ms=500,
             style="taker", notional_usd=DEFAULT_NOTIONAL_USD):
    model = load_model(model_path)
    cal = load_cal(cost_path)
    cost = cost_model(cal, notional_usd)
    gate = cost[style]["gate_bps"]
    
    df = pd.read_parquet(feature_path)
    df = add_labels(df)
    splits = chrono_split_masks(df)
    oos = df.loc[splits[2]["mask"]].reset_index(drop=True)
    
    pred = predict(model, oos, horizon_ms)
    y = oos["r_%d" % horizon_ms].to_numpy(float)
    
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": str(model_path),
        "cost_calibration": str(cost_path),
        "style": style,
        "notional_usd": float(notional_usd),
        "horizon_ms": horizon_ms,
        "gate_bps": gate,
        "cost_model": cost,
        "split_fractions": [0.7, 0.15, 0.15],
        "days": {s["name"]: {"lo_ms": int(df.loc[s["mask"], "ts_ms"].min()),
                             "hi_ms": int(df.loc[s["mask"], "ts_ms"].max()),
                             "rows": int(s["mask"].sum())} for s in splits},
        "blocks": {},
    }
    
    for name, spl in ((splits[1]["name"], df.loc[splits[1]["mask"]]),
                      (splits[2]["name"], oos)):
        p = predict(model, spl, horizon_ms)
        y_spl = spl["r_%d" % horizon_ms].to_numpy(float)
        gross = y_spl * np.sign(p)
        net = gross - gate
        valid = np.isfinite(net)
        net_valid = net[valid]
        n = int(valid.sum())
        
        sem = net_valid.std() / math.sqrt(n) if n > 0 else 0.0
        ci = stats.t.interval(0.95, max(0, n-1), loc=net_valid.mean(), scale=sem) if n > 1 else (0.0, 0.0)
        t_stat = net_valid.mean() / sem if sem > 0 else 0.0
        p_val = 2.0 * stats.t.sf(abs(t_stat), max(0, n-1)) if n > 1 else 1.0
        
        # Profit factor and drawdown
        wins = net_valid[net_valid > 0]
        losses = -net_valid[net_valid <= 0]
        pf = float(wins.sum() / losses.sum()) if losses.sum() > 0 \
            else (float("inf") if wins.sum() > 0 else 0.0)
        cum = np.cumsum(net_valid)
        peak = np.maximum.accumulate(cum)
        mdd = float(np.max(peak - cum)) if len(cum) > 0 else 0.0
        
        report["blocks"][name] = {
            "rows": int(len(spl)),
            "gross_expectancy_bps": round(float(np.nanmean(gross)), 6),
            "net_expectancy_bps": round(float(np.nanmean(net)), 6),
            "n_valid": n,
            "std_bps": round(float(np.nanstd(net)), 6),
            "sem_bps": round(float(sem), 6),
            "ci_95_low": round(float(ci[0]), 6),
            "ci_95_high": round(float(ci[1]), 6),
            "t_stat": round(float(t_stat), 6),
            "p_value": round(float(p_val), 6),
            "profit_factor": round(pf, 6),
            "max_drawdown_bps": round(mdd, 6),
            "long": _score(y_spl, p, gate, "long"),
            "short": _score(y_spl, p, gate, "short"),
        }
        
        # Regime breakdown
        regimes = {}
        for regime in spl["regime"].unique():
            m_regime = spl["regime"] == regime
            p_reg = p[m_regime]
            y_reg = y_spl[m_regime]
            gross_reg = y_reg * np.sign(p_reg)
            net_reg = gross_reg - gate
            valid_reg = np.isfinite(net_reg)
            if valid_reg.sum() > 0:
                regimes[regime] = {
                    "n": int(valid_reg.sum()),
                    "gross_mean_bps": round(float(gross_reg[valid_reg].mean()), 6),
                    "net_mean_bps": round(float(net_reg[valid_reg].mean()), 6),
                }
        report["blocks"][name]["regimes"] = regimes
    
    oosb = report["blocks"]["oos"]
    long_n, short_n = oosb["long"]["n"], oosb["short"]["n"]
    net = oosb["net_expectancy_bps"]
    conclude = long_n >= 200 and short_n >= 200
    report["verdict"] = ("STOP" if (conclude and net <= 0)
                         else ("PASS" if conclude and net > 0
                               else "INSUFFICIENT"))
    
    out_path = Path(out_path)
    out_path.write_text(json.dumps(report, indent=1))
    return report


if __name__ == "__main__":
    model_path = DATA_RESEARCH / "v3_model.json"
    cost_path = DATA_HIST_RESEARCH / "execution_calibration.json"
    feature_path = DATA_RESEARCH / "v3_features.parquet"
    out_path = DATA_RESEARCH / "V3_OOS_CORRECTED.json"
    
    r = validate(model_path, cost_path, feature_path, out_path)
    oosb = r["blocks"]["oos"]
    print(json.dumps({
        "verdict": r["verdict"],
        "oos_net_expectancy_bps": oosb["net_expectancy_bps"],
        "ci_95": [oosb["ci_95_low"], oosb["ci_95_high"]],
        "t_stat": oosb["t_stat"],
        "p_value": oosb["p_value"],
        "profit_factor": oosb["profit_factor"],
        "max_drawdown_bps": oosb["max_drawdown_bps"],
        "long_n": oosb["long"]["n"],
        "short_n": oosb["short"]["n"],
        "gate_bps": r["gate_bps"],
        "regimes": oosb["regimes"],
    }, indent=1))
