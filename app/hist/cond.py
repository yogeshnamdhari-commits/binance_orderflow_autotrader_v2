"""Conditional-expectancy research on authentic aggTrades (Dataset A).

For every trade on a verified day we compute:
- aggressor-direction features: delta over 1s/5s windows, buy-volume share,
  trade intensity, delta acceleration (1s-to-1s bin change),
- forward trade-price returns at 5/15/60s (two-pointer scan; price source =
  aggregate-trade price, explicitly NOT mid/L2),
- MFE/MAE on trade prices over the 15s window (monotone deque, O(n)).

Then we measure whether each candidate condition predicts subsequent returns:
- decile tables per feature (does e.g. delta_5s level predict future returns?)
- boolean conditions: buy/sell exhaustion (strong one-sided flow that decelerates).

Expectancy is reported gross AND net of a round-trip cost model (taker fee +
slippage assumptions). No condition is assumed profitable; the table IS the test.
"""

import argparse
import json
import math
import statistics
import sys
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd

FEE_BPS = 2.0        # Binance USD-M futures taker fee, bps per side (assumption)
SLIP_BPS = 1.0       # assumed slippage, bps per side (modelled, not measured)
HORIZONS_MS = (5_000, 15_000, 30_000, 60_000)
BIN_MS = 1_000
W1 = 1               # 1s window = 1 bin
W5 = 5               # 5s window

AGGRADE_COLS = ["transact_time", "price", "quantity", "is_buyer_maker"]


def _forward_ptr(t, h):
    """n[ first j with t[j]-t[i] >= h ], else -1. Vectorized (sorted t)."""
    n = len(t)
    j = np.searchsorted(t, t + h, side="left")
    out = np.where(j < n, j, -1).astype(np.int64)
    return out


def _sliding_max_min(p, right):
    """For each i, max/min of p[i:right[i]] (right exclusive, non-decreasing; empty if right[i] <= i)."""
    n = len(p)
    mx = np.empty(n, dtype=np.float64)
    mn = np.empty(n, dtype=np.float64)
    dmax = deque()
    dmin = deque()
    rend_prev = 0
    for i in range(n):
        rend = right[i]
        hi = min(max(rend, i), n)
        lo = max(rend_prev, i)
        while dmax and dmax[0] < i:
            dmax.popleft()
        while dmin and dmin[0] < i:
            dmin.popleft()
        for k in range(lo, hi):
            while dmax and p[dmax[-1]] <= p[k]:
                dmax.pop()
            dmax.append(k)
            while dmin and p[dmin[-1]] >= p[k]:
                dmin.pop()
            dmin.append(k)
        rend_prev = hi
        if dmax:
            mx[i] = p[dmax[0]]
            mn[i] = p[dmin[0]]
        else:
            mx[i] = mn[i] = p[i]
    return mx, mn


def build_day(parquet, bin_ms=BIN_MS, need_span=True):
    df = pd.read_parquet(parquet, columns=AGGRADE_COLS)
    df = df.sort_values("transact_time").reset_index(drop=True)
    t = df["transact_time"].to_numpy(np.int64)
    p = df["price"].to_numpy(np.float64)
    q = df["quantity"].to_numpy(np.float64)
    maker = df["is_buyer_maker"].to_numpy(np.bool_)
    qv = np.where(~maker, q, -q)

    # ---- bin aggregation (1-s bins) ----
    t0 = int(t[0])
    bin_id = ((t - t0) // bin_ms).astype(np.int64)
    nbins = int(bin_id[-1]) + 1
    bin_delta = np.zeros(nbins)
    bin_buyvol = np.zeros(nbins)
    bin_totvol = np.zeros(nbins)
    bin_cnt = np.zeros(nbins, dtype=np.int64)
    np.add.at(bin_delta, bin_id, qv)
    np.add.at(bin_buyvol, bin_id, np.where(qv > 0, q, 0.0))
    np.add.at(bin_totvol, bin_id, q)
    np.add.at(bin_cnt, bin_id, 1)

    bin_open = np.full(nbins, np.nan)
    first_rows = np.flatnonzero(np.concatenate(([True], np.diff(bin_id) != 0)))
    bin_open[np.unique(bin_id)] = p[first_rows]

    # rolling trailing sums over last W bins, edges clipped
    cs_d = np.concatenate(([0.0], np.cumsum(bin_delta)))
    cs_b = np.concatenate(([0.0], np.cumsum(bin_buyvol)))
    cs_v = np.concatenate(([0.0], np.cumsum(bin_totvol)))
    cs_c = np.concatenate(([0.0], np.cumsum(bin_cnt)))

    rolling = {}
    for W in (W1, W5):
        start = np.arange(nbins) + 1
        i0 = np.clip(start - W, 0, nbins)
        rolling[(W, "d")] = cs_d[start] - cs_d[i0]
        rolling[(W, "b")] = cs_b[start] - cs_b[i0]
        rolling[(W, "v")] = cs_v[start] - cs_v[i0]
        rolling[(W, "c")] = cs_c[start] - cs_c[i0]
    rolling["acc"] = np.concatenate(([0.0], np.diff(bin_delta)))

    iB = bin_id
    delta_1s = rolling[(W1, "d")][iB]
    delta_5s = rolling[(W5, "d")][iB]
    buyshare_5s = np.divide(rolling[(W5, "b")][iB], rolling[(W5, "v")][iB],
                            out=np.full(len(iB), np.nan), where=rolling[(W5, "v")][iB] > 0)
    intensity_5s = rolling[(W5, "c")][iB] / (W5 * bin_ms / 1000.0)
    accel = rolling["acc"][iB]

    # ---- forward returns + excursion spans (max/min trade price over each window) ----
    ret = {}
    span = {}
    mfe15 = mae15 = None
    for h in HORIZONS_MS:
        fp = _forward_ptr(t, h)
        ok = fp > 0
        j = np.clip(fp, 0, len(t) - 1)
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = np.where(ok, p[j] / bin_open[bin_id] - 1.0, np.nan)
        ret[h] = ratio
        if need_span:
            rp = np.where(fp > 0, fp, len(t))
            mx, mn = _sliding_max_min(p, rp)
            span[h] = (mx, mn)
            if h == 15_000:
                mfe15 = (mx / p - 1.0) * 1e4
                mae15 = (mn / p - 1.0) * 1e4

    return {"t": t, "p": p, "qv": qv, "maker": maker,
            "delta_1s": delta_1s, "delta_5s": delta_5s,
            "buyshare_5s": buyshare_5s, "intensity_5s": intensity_5s,
            "accel": accel, "r": ret, "mfe15": mfe15, "mae15": mae15,
            "span": span}


def round_trip_cost_bps():
    return 2.0 * (FEE_BPS + SLIP_BPS)


def deciles(feat):
    x = feat
    x = x[np.isfinite(x)]
    if len(x) < 10:
        return None
    edges = np.quantile(x, np.linspace(0, 1, 11))
    if len(np.unique(edges)) < 5:
        return None
    return edges


def decile_expectancy(builder, feat_key, horizon=15_000):
    """Per-decile mean/net return. Returns list of dict rows."""
    r = builder["r"][horizon]
    edges = deciles(builder[feat_key])
    if edges is None:
        return []
    idx = np.searchsorted(edges, builder[feat_key], side="right") - 1
    cost = round_trip_cost_bps() / 1e4
    rows = []
    for d in range(10):
        sel = (idx == d) & np.isfinite(r)
        n = int(np.sum(sel))
        if n == 0:
            continue
        rs = r[sel]
        gross = np.nanmean(rs) * 1e4
        med = float(np.nanmedian(rs)) * 1e4
        sd = float(np.nanstd(rs))
        tstat = float(np.nanmean(rs) / (sd / math.sqrt(n))) if sd and n > 1 else 0.0
        rows.append({"decile": d + 1, "n": n,
                     "gross_mean_bps": round(gross, 3),
                     "net_mean_bps": round((gross - cost * 1e4), 3),
                     "median_bps": round(med, 3),
                     "t_stat": round(tstat, 3),
                     "hit_rate": round(float(np.mean(rs > 0)) * 100, 1),
                     "mfe15_avg_bps": round(float(np.nanmean(builder["mfe15"][sel])) if np.isfinite(builder["mfe15"][sel]).any() else np.nan, 2),
                     "mae15_avg_bps": round(float(np.nanmean(builder["mae15"][sel])) if np.isfinite(builder["mae15"][sel]).any() else np.nan, 2)})
    return rows


def exhaustion_expectancy(builder, horizon=15_000):
    """Strong one-sided flow that decelerates. Returns (buy_rows, sell_rows)."""
    cost = round_trip_cost_bps() / 1e4
    persec = 0.5 * (builder["delta_5s"] / W5)
    buy = (builder["buyshare_5s"] >= 0.8) & (builder["delta_1s"] < persec)
    sell = (builder["buyshare_5s"] <= 0.2) & (builder["delta_1s"] > -persec)

    def one(mask, label):
        r = builder["r"][horizon]
        sel = mask & np.isfinite(r)
        n = int(np.sum(sel))
        if n == 0:
            return None
        rs = r[sel]
        gross = float(np.nanmean(rs)) * 1e4
        sd = float(np.nanstd(rs))
        return {"condition": label, "n": n,
                "gross_mean_bps": round(gross, 3),
                "net_mean_bps": round(gross - cost * 1e4, 3),
                "median_bps": round(float(np.nanmedian(rs)) * 1e4, 3),
                "t_stat": round(gross / 1e4 / (sd / math.sqrt(n)), 3) if sd and n > 1 else 0.0,
                "hit_rate": round(float(np.mean(rs > 0)) * 100, 1),
                "mfe15_avg_bps": round(float(np.nanmean(builder["mfe15"][sel])), 2),
                "mae15_avg_bps": round(float(np.nanmean(builder["mae15"][sel])), 2)}
    return one(buy, "BUY_exhaustion"), one(sell, "SELL_exhaustion")


def day_research(parquet):
    bd = build_day(parquet)
    features = ("delta_5s", "buyshare_5s", "intensity_5s", "accel")
    out = {"day": Path(parquet).name.split("-")[-1].replace(".parquet", "")}
    for f in features:
        out[f] = decile_expectancy(bd, f)
    eb, es = exhaustion_expectancy(bd)
    out["exhaustion"] = {"buy": eb, "sell": es}
    return out


def condition_mask(builder, feat_key, decile):
    """Boolean mask for events in the given decile (1..10) of a feature."""
    edges = deciles(builder[feat_key])
    if edges is None:
        return None
    idx = np.searchsorted(edges, builder[feat_key], side="right") - 1
    return idx == decile - 1


def thin_indices(t, mask, horizon):
    """Greedy non-overlapping picks: consecutive picks >= horizon ms apart in time."""
    i = np.flatnonzero(mask)
    if len(i) == 0:
        return i
    last = t[i[0]] - horizon
    keep = mask
    pick = []
    for x in i:
        if t[x] >= last + horizon:
            pick.append(x)
            last = t[x]
    return np.asarray(pick, dtype=np.int64)


def event_stats(rs):
    """Full per-event stat suite over a returns array (already bps). Compatible with [] inputs."""
    rs = np.asarray(rs, dtype=np.float64)
    rs = rs[np.isfinite(rs)]
    n = len(rs)
    if n == 0:
        return None
    mean = float(np.mean(rs))
    sd = float(np.std(rs, ddof=1)) if n > 1 else 0.0
    med = float(np.median(rs))
    pos = rs[rs > 0]
    neg = rs[rs < 0]
    pf = float(np.sum(pos) / abs(np.sum(neg))) if len(neg) and np.sum(pos) else np.nan
    return {"n": n,
            "gross_mean_bps": round(mean, 3),
            "median_bps": round(med, 3),
            "sd_bps": round(sd, 3),
            "t_stat": round(mean / (sd / math.sqrt(n)), 3) if sd else 0.0,
            "sharpe": round(mean / sd * math.sqrt(n), 3) if sd else 0.0,
            "hit_rate": round(float(np.mean(rs > 0)) * 100, 1),
            "profit_factor": round(pf, 3) if not math.isnan(pf) else None,
            "p5_bps": round(float(np.percentile(rs, 5)), 1),
            "p95_bps": round(float(np.percentile(rs, 95)), 1)}


def exhaustion_mask(builder):
    """Booleans for buy-exhaustion (strong buys decelerating) and sell-exhaustion."""
    persec = 0.5 * (builder["delta_5s"] / W5)
    buy = (builder["buyshare_5s"] >= 0.8) & (builder["delta_1s"] < persec)
    sell = (builder["buyshare_5s"] <= 0.2) & (builder["delta_1s"] > -persec)
    return buy, sell


def condition_trades(builder, feat_key, decile, horizon, direction):
    """Thinned (non-overlapping) returns, bps, for a decile condition in a direction.
    direction: +1 long, -1 short. Returns (events_returns, thinned_idx, mask_before_thinning)."""
    mask = condition_mask(builder, feat_key, decile)
    if mask is None:
        return None, None, None
    r = builder["r"][horizon]
    sel = mask & np.isfinite(r)
    idx = thin_indices(builder["t"], sel, horizon)
    if len(idx) == 0:
        return np.array([]), idx, sel
    returns = (r[idx] * direction) * 1e4
    return returns, idx, sel


def excursion_bps(builder, idx, horizon, direction):
    """Mean favorable/adverse excursion (bps) for thinned events in a direction.
    Uses the max/min trade price inside each [entry, exit) window (builder['span'])."""
    if len(idx) == 0:
        return np.array([]), np.array([])
    mx, mn = builder["span"][horizon]
    entry = builder["p"][idx]
    fav = np.where(direction > 0, (mx[idx] - entry), (entry - mn[idx])) / entry * 1e4
    adv = np.where(direction > 0, (entry - mn[idx]), (mx[idx] - entry)) / entry * 1e4
    return np.asarray(fav, dtype=np.float64), np.asarray(adv, dtype=np.float64)