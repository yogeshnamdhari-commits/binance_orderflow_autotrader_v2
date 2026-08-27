"""V5 features — predeclared, causality-preserving order-flow evidence stack.

Primary feature set, fixed BEFORE any OOS examination, grounded in
Cont-Kukanov-Stoikov (OFI -> short-horizon price impact, inversely to depth)
and queue-imbalance microstructure literature. All features are computed only
from events with strictly-earlier timestamps (trailing windows) — no look-ahead:

  ofi_l1 / ofi_norm_l1   OFI and depth-normalized OFI (impact / depth logic)
  qi_l1                  queue imbalance at the touch
  di_l5 / di_l10         distance-weighted multi-level depth imbalance
  mpd_bps                microprice offset from mid
  spread_bps             (ask-bid)/mid
  bid_cancel_bps/ask_add_bps/cancel_pressure   cancel and add pressure
  tfi_500                trade-flow imbalance over the trailing 500 ms
  liq_depletion          near-touch depth consumed by recent aggressors / depth5
  log_depth1/log_depth5  log liquidity
  log_event_rate         event activity
  depth_slope_bps        log-depth decay (liquidity shape)
  vol_500 / vol_2000     trailing short-horizon realized volatility of mid
                         log-returns (causal; literature: impact relative to vol)

NO technical indicators, no RSI/EMA/VWAP, no forward references.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

COLUMNS = ["ts_ms", "recv_ms", "session", "kind", "seq",
           "best_bid", "best_ask", "mid", "microb_price", "spread_bps",
           "mpd_bps", "qi_l1", "di_l5", "di_l10", "depth_slope_bps",
           "ofi_l1", "ofi_norm_l1", "bid_add_bps", "bid_cancel_bps",
           "ask_add_bps", "ask_cancel_bps", "cancel_pressure",
           "log_depth1", "log_depth5", "log_event_rate",
           "tfi_500", "signed_vol_500", "trade_rate", "liq_depletion",
           "regime", "vol_500", "vol_2000"]

V5_FEATURES = ["ofi_l1", "ofi_norm_l1", "qi_l1", "di_l5", "di_l10",
               "mpd_bps", "spread_bps", "bid_cancel_bps", "ask_add_bps",
               "cancel_pressure", "tfi_500", "liq_depletion",
               "log_depth1", "log_depth5", "log_event_rate",
               "depth_slope_bps", "vol_500"]

HORIZONS_MS = (250, 500, 1000)


def add_trailing_vol(df, windows=(500, 2000)):
    """Causal trailing realized vol (bps) of mid log-returns per session.

    For event i within a session, vol_w = sqrt(sum over consecutive-event
    log-returns of mid in (ts-w, ts]) * 1e4 from the raw mid series. Only
    events with ts < current ts are used; the window start is ts-w so pushes
    zero reference ahead. Missing (warm-up) rows become NaN (dropped by the
    model's finite-mask), not partial zeros.
    """
    df = df.copy()
    for w in windows:
        col = "vol_%d" % w
        out = np.full(len(df), np.nan)
        idx = 0
        for sname, grp in df.groupby("session", sort=True):
            ts = grp["ts_ms"].to_numpy(dtype=np.int64)
            mid = grp["mid"].to_numpy(dtype=float)
            lr = np.zeros(len(ts))
            m = (mid > 0) & np.isfinite(mid)
            lr[1:] = np.where(m[1:] & m[:-1] & (ts[1:] > ts[:-1]),
                              np.log(mid[1:] / mid[:-1]), 0.0)
            j = 0
            for i in range(len(ts)):
                while j < i and ts[j] < ts[i] - w:
                    j += 1
                seg = lr[j:i]  # strictly < ts[i]
                if (i - j) >= 3:
                    out[idx + i] = np.sqrt(np.sum(seg ** 2)) * 1e4
            idx += len(ts)
        df[col] = out
    return df


def build_features(out_path, session_dirs):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frames = []
    for sd in session_dirs:
        sd = Path(sd)
        dv = sd / "derived_v5.jsonl"
        if not dv.exists():
            continue
        rows = [json.loads(l) for l in dv.open() if l.strip()]
        df = pd.DataFrame(rows)
        df["session"] = sd.name
        frames.append(df)
    if not frames:
        raise ValueError("no v5 derived rows")
    df = pd.concat(frames, ignore_index=True)
    df["seq"] = df["seq"].astype(str)
    df = df[COLUMNS[:COLUMNS.index("vol_500")]] \
        .sort_values(["session", "ts_ms"]).reset_index(drop=True)
    df = add_trailing_vol(df)
    df.to_parquet(out_path, index=False)
    return out_path


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path,
                    default=Path("data/research/v5_features.parquet"))
    ap.add_argument("sessions", nargs="+", type=Path)
    a = ap.parse_args()
    p = build_features(a.out, a.sessions)
    print("wrote", p)