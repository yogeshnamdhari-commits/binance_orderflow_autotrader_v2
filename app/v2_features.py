"""V2 Phase-2 feature engine.

Consumes authenticated event-linked V2 collector sessions (a dir containing
raw.jsonl + derived.jsonl + session.json) and emits a research parquet with one
row per book/trade event carrying the frozen V2 feature set:

  Flow / liquidity state:
    nofi_1, nofi_5, nofi_10   depth-normalized OFI at level sets L1/L5/L10
    qi1, qi5, qi10            queue imbalance at L1/L5/L10
    mpd_bps, microb_price     micro-price displacement (basis points) + level
    spread_bps, depth1/5/10   liquidity state
    tfi_250/500/1000          aggressive trade-flow imbalance @ declared horizons
    (buy|sell)_vol_250/500/1000
    book_rate, trade_rate     event intensity (events/sec in trailing 1s)
    latency_ms                recv_ms - exchange_event_ms (record resolution)

Model-ready columns (frozen transforms):
    nofi_1, nofi_5, nofi_10, tfi_500, qi1, qi5, qi10, mpd_bps, spread_bps,
    log_depth10 = log1p(depth10), log_event_rate = log1p(book_rate + trade_rate)

TFI horizons, label horizons and the intensity window are predeclared
constants. Nothing here is selected on outcome data.
"""

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

TFI_HORIZONS_MS = (250, 500, 1000)
MODEL_TFI_MS = 500
EVENT_WINDOW_MS = 1000
LABEL_HORIZONS_MS = (250, 500, 1000)

MODEL_FEATURES = ["nofi_1", "nofi_5", "nofi_10", "tfi_500",
                  "qi1", "qi5", "qi10", "mpd_bps", "spread_bps",
                  "log_depth10", "log_event_rate"]


def _load_jsonl(path):
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _window_sums(ts_arr, pref_buy, pref_sell, t, h):
    lo = int(np.searchsorted(ts_arr, t - h, side="left"))
    hi = int(np.searchsorted(ts_arr, t, side="right"))
    buy = pref_buy[hi] - pref_buy[lo]
    sell = pref_sell[hi] - pref_sell[lo]
    return buy, sell


def _tfi(buy, sell):
    tot = buy + sell
    return (buy - sell) / tot if tot else 0.0


def _session_events(session_dir, log=print):
    session_dir = Path(session_dir)
    derived = _load_jsonl(session_dir / "derived.jsonl")
    raw = _load_jsonl(session_dir / "raw.jsonl")
    session = session_dir.name
    if not derived:
        return []

    derived.sort(key=lambda r: (r["ts_ms"], r.get("recv_ms", 0)))

    trades = sorted((r["T"], float(r["q"]), bool(r["m"]), r["recv_ms"])
                    for r in raw if r.get("kind") == "trade")
    t_ts = np.array([t for t, _, _, _ in trades], dtype=np.int64)
    t_buy = np.array([q if not m else 0.0 for _, q, m, _ in trades], dtype=float)
    t_sell = np.array([q if m else 0.0 for _, q, m, _ in trades], dtype=float)
    pref_buy = np.concatenate([[0.0], np.cumsum(t_buy)])
    pref_sell = np.concatenate([[0.0], np.cumsum(t_sell)])

    d_ts = np.array([r["ts_ms"] for r in derived], dtype=np.int64)
    dep_ts = np.array([r["ts_ms"] for r in derived if r["kind"] == "depth"], dtype=np.int64)
    trd_ts = np.array([r["ts_ms"] for r in derived if r["kind"] == "trade"], dtype=np.int64)

    out = []
    for i, r in enumerate(derived):
        t = r["ts_ms"]
        if r.get("mid") is None:
            continue
        d5 = r.get("bid_depth5", 0.0) + r.get("ask_depth5", 0.0)
        d10 = r.get("bid_depth10", 0.0) + r.get("ask_depth10", 0.0)
        d1 = r.get("bid_depth1", 0.0) + r.get("ask_depth1", 0.0)
        row = {
            "session": session,
            "ts_ms": t,
            "kind": r["kind"],
            "seq": r.get("seq"),
            "recv_ms": r.get("recv_ms", 0),
            "latency_ms": (r.get("recv_ms", 0) or 0) - t,
            "mid": r["mid"],
            "best_bid": r.get("best_bid"), "best_ask": r.get("best_ask"),
            "spread_bps": r.get("spread_bps"),
            "microb_price": r.get("microb_price"), "mpd_bps": r.get("mpd_bps"),
            "depth1": round(d1, 8), "depth5": round(d5, 8), "depth10": round(d10, 8),
            "qi1": r.get("qi1"), "qi5": r.get("qi5"), "qi10": r.get("qi10"),
            "ofi_l1": r.get("ofi_l1", 0.0), "ofi_l5": r.get("ofi_l5", 0.0),
            "ofi_l10": r.get("ofi_l10", 0.0), "ofi_net": r.get("ofi_net", 0.0),
            "ofi_depth": r.get("ofi_depth", 0.0),
        }
        def norm(ofi, dep):
            return round(ofi / dep, 8) if dep else 0.0
        row["nofi_1"] = norm(r.get("ofi_l1", 0.0), d1)
        row["nofi_5"] = norm(r.get("ofi_l5", 0.0), d5)
        row["nofi_10"] = norm(r.get("ofi_l10", 0.0), d10)

        for h in TFI_HORIZONS_MS:
            buy, sell = _window_sums(t_ts, pref_buy, pref_sell, t, h)
            row["buy_vol_%d" % h] = round(buy, 8)
            row["sell_vol_%d" % h] = round(sell, 8)
            row["tfi_%d" % h] = round(_tfi(buy, sell), 6)

        nb = int(np.searchsorted(dep_ts, t - EVENT_WINDOW_MS, side="left"))
        nbh = int(np.searchsorted(dep_ts, t, side="right"))
        nt = int(np.searchsorted(trd_ts, t - EVENT_WINDOW_MS, side="left"))
        nth = int(np.searchsorted(trd_ts, t, side="right"))
        row["book_rate"] = round((nbh - nb) * 1000.0 / EVENT_WINDOW_MS, 4)
        row["trade_rate"] = round((nth - nt) * 1000.0 / EVENT_WINDOW_MS, 4)

        row["log_depth10"] = math.log1p(max(d10, 0.0))
        row["log_event_rate"] = math.log1p(row["book_rate"] + row["trade_rate"])
        out.append(row)
    return out


def build_session_features(feature_path, session_dirs, log=print):
    feature_path = Path(feature_path)
    feature_path.parent.mkdir(parents=True, exist_ok=True)
    all_rows = []
    for sd in session_dirs:
        rows = _session_events(sd, log=log)
        log("features %s: %d event rows" % (Path(sd).name, len(rows)))
        all_rows.extend(rows)
    if not all_rows:
        raise ValueError("no feature rows produced from %d session(s)" % len(session_dirs))
    df = pd.DataFrame(all_rows)
    df["ts_ms"] = df["ts_ms"].astype("int64")
    df["seq"] = df["seq"].apply(lambda s: None if s is None else str(s))
    df = df.sort_values(["ts_ms", "recv_ms"]).reset_index(drop=True)
    df.to_parquet(feature_path, index=False)
    return feature_path


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("data/hist/research/v2_features.parquet"))
    ap.add_argument("sessions", nargs="+", type=Path)
    a = ap.parse_args()
    build_session_features(a.out, a.sessions)