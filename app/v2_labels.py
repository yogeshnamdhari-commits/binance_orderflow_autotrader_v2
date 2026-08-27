"""V2 Phase-2 label engine.

Appends strictly-future outcomes to the feature parquet and writes a separate
v2_labels.parquet so features and labels are auditable independently.

For each event at time t, at every predeclared horizon h in
LABEL_HORIZONS_MS = (250, 500, 1000):

  r_h   = (mid_{first event >= t+h} - mid_t) / mid_t * 1e4     # bps
  m_h   = (microb_{first event >= t+h} - microb_t) / microb_t * 1e4

Only events that have a strictly-future reference at every horizon keep a
label; the trailing tail loses labels and is not used in training. No event's
label is computed with any information from its own timestamp or earlier.
"""

import numpy as np
import pandas as pd
from pathlib import Path

from .v2_features import LABEL_HORIZONS_MS


def add_labels(features_df, horizons=LABEL_HORIZONS_MS):
    df = features_df.sort_values("ts_ms").reset_index(drop=True)
    ts = df["ts_ms"].to_numpy(dtype=np.int64)
    mid = df["mid"].to_numpy(dtype=float)
    microb = df["microb_price"].to_numpy(dtype=float)
    n = len(df)
    idx = np.arange(n, dtype=np.int64)
    for h in horizons:
        ptr = np.searchsorted(ts, ts + h, side="left")
        valid = ptr < n
        r = np.full(n, np.nan)
        fut_mid = np.full(n, np.nan)
        r[valid] = (mid[ptr[valid]] - mid[valid]) / mid[valid] * 1e4
        fut_mid[valid] = mid[ptr[valid]]
        m = np.full(n, np.nan)
        fut_m = np.full(n, np.nan)
        mb_ok = valid & np.isfinite(microb)
        m[mb_ok] = (microb[ptr[mb_ok]] - microb[mb_ok]) / microb[mb_ok] * 1e4
        fut_m[mb_ok] = microb[ptr[mb_ok]]
        df["r_%d" % h] = r
        df["m_%d" % h] = m
        df["future_mid_%d" % h] = fut_mid
        df["future_microb_%d" % h] = fut_m
    return df


def write_labels(labels_path, features_df, horizons=LABEL_HORIZONS_MS):
    labels_path = Path(labels_path)
    df = add_labels(features_df, horizons)
    keep = ["ts_ms", "session", "kind", "mid", "microb_price"] + \
           ["r_%d" % h for h in horizons] + ["m_%d" % h for h in horizons]
    df[keep].to_parquet(labels_path, index=False)
    return labels_path


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", type=Path, default=Path("data/hist/research/v2_features.parquet"))
    ap.add_argument("--out", type=Path, default=Path("data/hist/research/v2_labels.parquet"))
    a = ap.parse_args()
    write_labels(a.out, pd.read_parquet(a.features))