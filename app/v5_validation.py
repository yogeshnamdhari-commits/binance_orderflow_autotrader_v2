"""V5 validation — untouched-OOS economic evaluation of the frozen model.

Scoreboard (all on the OOS slice ..., ts strictly inside OOS per v3 split):
  gross expectancy  = sign-of-prediction mean directional label
  gated expectancy  = net of trades the strategy actually takes after the
                      measured gate (LONG/SHORT only) minus gate
  execution rate / per-direction counts (LONG/SHORT need >= 200 each)
  per-session net (executed) and largest-session dominance share
  PF / Sharpe / max DD on the executed net series (non-overlapping subsample
    at primary horizon, so overlap doesn't inflate Sharpe)
Cost sensitivity & walk-forward are analysis artifacts computed by the
economic report, never used in the verdict.
"""

import numpy as np
import pandas as pd

from .v3_model import chrono_split_masks
from .v5_model import PRIMARY_HORIZON


def oos_frame(feature_path, model_d):
    df = pd.read_parquet(feature_path)
    for h in model_d["label_horizons_ms"]:
        if "r_%d" % h not in df:
            from .v3_labels import add_labels
            df = add_labels(df, model_d["label_horizons_ms"])
    splits = chrono_split_masks(df)
    oos_spl = None
    for s in splits:
        if s["name"] == "oos":
            oos_spl = s
    return df.loc[oos_spl["mask"]].reset_index(drop=True), oos_spl


def non_overlap_keep(df, horizon_ms=PRIMARY_HORIZON):
    keep, last = [], None
    for _, r in df.iterrows():
        if last is None or r["ts_ms"] - last >= horizon_ms:
            keep.append(r.name)
            last = r["ts_ms"]
    return df.loc[keep]


def scoreboard(oos, pred, gate):
    """Indexed by the strategy decision state (LONG/SHORT/NO_TRADE by |pred|>gate)."""
    lbl = {}
    for h in oos.columns:
        if h.startswith("r_"):
            lbl[h] = h
    h = PRIMARY_HORIZON
    r = oos
    y = r["r_%d" % h].to_numpy(float)
    states = np.where(pred > gate, "LONG", np.where(pred < -gate, "SHORT", "NO_TRADE"))
    gross = np.where(np.sign(pred) == 0, 0.0, np.sign(pred))
    gross_move = gross * y
    executed = states != "NO_TRADE"
    net_exe = (np.where(executed, 0.0, 0.0) +
               np.where(executed, np.sign(pred) * y - gate, 0.0))
    sb = {
        "horizon_ms": h, "gate_bps": gate, "oos_rows": int(len(r)),
        "executed_rows": int(executed.sum()), "no_trade_rows": int((~executed).sum()),
        "gross_dir_n": int((pred != 0).sum()),
        "gross_expectancy_bps": float(np.nanmean(gross_move)),
        "gross_std_bps": float(np.nanstd(gross_move)),
        "gated_expectancy_bps": float(net_exe[executed].mean())
        if executed.any() else 0.0,
        "gated_std_bps": float(net_exe[executed].std()) if executed.any() else 0.0,
        "per_direction": {},
        "per_session": {},
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
    for s in r["session"].unique():
        m = r["session"] == s
        em = m.to_numpy() & executed
        sess[s] = {"rows": int(m.sum()), "executed_rows": int(em.sum()),
                   "gross_bps": float(np.nanmean(gross_move[m.to_numpy()])),
                   "net_bps": float(np.nanmean(net_exe[em])) if em.any() else 0.0}
    sb["per_session"] = sess
    tot_exe = max(1, int(executed.sum()))
    sb["largest_session_share"] = float(max(v["executed_rows"]
                                            for v in sess.values()) / tot_exe)
    # risk statistics on a non-overlapping executed trail
    nomask = executed
    ex = r.loc[nomask]
    k = non_overlap_keep(ex.reset_index(drop=True), horizon_ms=h)
    trail = (np.sign(pred[nomask]) * y[nomask] - gate)[k.index.to_numpy()]
    sb["pf"] = (float(trail[trail > 0].sum() / -trail[trail < 0].sum())
                if (trail[trail < 0].sum()) != 0 else
                (float("inf") if (trail[trail > 0].sum()) > 0 else 0.0))
    sb["sharpe"] = float(trail.mean() / trail.std()) if len(trail) > 1 and trail.std() > 0 else 0.0
    sb["max_drawdown_bps"] = float(_maxdd(trail))
    sb["net_trail_n"] = int(len(trail))
    return sb


def _maxdd(trail):
    if len(trail) == 0:
        return 0.0
    s, peak, mdd = 0.0, 0.0, 0.0
    for x in trail:
        s += x
        peak = max(peak, s)
        mdd = max(mdd, peak - s)
    return mdd