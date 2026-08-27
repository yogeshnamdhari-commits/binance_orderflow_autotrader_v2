"""V3 label engine — strictly-future outcomes at predeclared horizons.

For each event at time t and each predeclared horizon h in
PREDECLARED_HORIZONS_MS = (250, 500, 1000):

  r_h   = (mid_{first event >= t+h} - mid_t) / mid_t * 1e4     # forward bps
  m_h   = (microb_{first event >= t+h} - microb_t) / microb_t * 1e4

Horizons are set by the event-time distribution and execution latency of the
system, NOT chosen for profitability. Tail events without a strictly-future
reference at every horizon lose their label. No event's label uses information
from its own timestamp or earlier.
"""

import numpy as np
import pandas as pd
from pathlib import Path

from .v3_features import PREDECLARED_HORIZONS_MS


def add_labels(df, horizons=PREDECLARED_HORIZONS_MS):
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


def write_labels(out_path, features_df, horizons=PREDECLARED_HORIZONS_MS):
    out_path = Path(out_path)
    df = add_labels(features_df, horizons)
    keep = ["ts_ms", "session", "kind", "mid", "microb_price"] + \
           ["r_%d" % h for h in horizons] + ["m_%d" % h for h in horizons]
    df[keep].to_parquet(out_path, index=False)
    return out_path


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", type=Path,
                    default=Path("data/research/v3_features.parquet"))
    ap.add_argument("--out", type=Path,
                    default=Path("data/research/v3_labels.parquet"))
    a = ap.parse_args()
    p = write_labels(a.out, pd.read_parquet(a.features))
    print("wrote", p)