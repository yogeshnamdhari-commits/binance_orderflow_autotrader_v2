"""V2 OOS robustness decomposition (Task 9).

Checks whether any positive OOS expectancy is stable or an artifact of one
lucky condition. Slices the OOS signal set by PRE-DECLARED, TRAIN-DEFINED
condition terciles (liquidity / spread / short-term volatility) plus 2
contiguous time blocks, and tabulates realized (post-cost) net P&L per cell.

Condition boundaries are locked from TRAIN so robustness cannot adapt to OOS.
"""

import numpy as np

VOL_WINDOW = 50
VOL_LABEL = "r_250"
MIN_CELL_N = 20
TIME_BLOCKS = 2


def _terciles(x):
    x = np.asarray(x, dtype=float)
    q = np.nanpercentile(x, [33.33, 66.67])
    return np.array([-np.inf, q[0], q[1], np.inf])


def condition_edges(train):
    """Locked train-defined boundaries: liquidity (depth10), spread, vol."""
    liquidity = np.asarray(train["liquidity"], dtype=float)
    spread = np.asarray(train["spread_bps"], dtype=float)
    vol = _rolling_vol(train)
    return {"liquidity": _terciles(liquidity), "spread": _terciles(spread),
            "vol": _terciles(vol)}


def _rolling_vol(ev):
    r = np.asarray(ev[VOL_LABEL], dtype=float)
    v = np.zeros(len(r))
    acc = 0.0
    for i in range(len(r)):
        acc += r[i] ** 2
        if i >= VOL_WINDOW:
            acc -= r[i - VOL_WINDOW] ** 2
        v[i] = np.sqrt(max(acc, 0.0) / min(VOL_WINDOW, i + 1))
    return v


def _labels(ev):
    return np.asarray(ev["label"], dtype=float)


def decompose(oos, train_edges, costs):
    """Returns per-cell realized net bps (taker) rows keyed by condition."""
    long_mask = np.asarray(oos["pred"] > 0.0)
    short_mask = np.asarray(oos["pred"] < 0.0)
    label = _labels(oos)
    liquidity = np.asarray(oos["liquidity"], dtype=float)
    spread = np.asarray(oos["spread_bps"], dtype=float)
    vol = _rolling_vol(oos)
    ts = np.asarray(oos["ts"], dtype=float)

    cells = []
    # time blocks
    lo, hi = ts.min(), ts.max()
    half = (hi - lo) / 2.0
    for b in range(TIME_BLOCKS):
        m = (ts >= lo + b * half) & (ts < lo + (b + 1) * half)
        _add_cell(cells, f"time_block_{b}", m, long_mask, short_mask, label, costs)
    # liquidity / spread / vol terciles
    for cond, arr, edges in [("liquidity", liquidity, train_edges["liquidity"]),
                             ("spread", spread, train_edges["spread"]),
                             ("vol", vol, train_edges["vol"])]:
        q = np.asarray(arr, dtype=float)
        for bkt in range(len(edges) - 1):
            lo_e, hi_e = edges[bkt], edges[bkt + 1]
            m = (q >= lo_e) & (q < hi_e)
            m &= np.isfinite(q)
            _add_cell(cells, f"{cond}_tercile{bkt}", m, long_mask, short_mask,
                      label, costs)
    return cells


def _add_cell(cells, name, m, long_mask, short_mask, label, costs):
    m = np.asarray(m, dtype=bool)
    ok = np.isfinite(label)
    m &= ok
    net_long = (label[m & long_mask] - costs["taker_bps"]) if (m & long_mask).any() \
        else np.array([])
    net_short = (-label[m & short_mask] - costs["taker_bps"]) if (m & short_mask).any() \
        else np.array([])
    net = np.concatenate([net_long, net_short])
    if not len(net):
        cells.append({"name": name, "n": 0, "long_n": 0, "short_n": 0,
                      "net_mean_bps": None, "net_std_bps": None,
                      "gross_mean_bps": None})
        return
    gross = np.concatenate([label[m & long_mask],
                            -label[m & short_mask]]) if len(net) else np.array([])
    cells.append({"name": name, "n": int(len(net)),
                  "long_n": int(len(net_long)),
                  "short_n": int(len(net_short)),
                  "net_mean_bps": float(net.mean()),
                  "net_std_bps": float(net.std()) if len(net) > 1 else None,
                  "gross_mean_bps": float(gross.mean()) if len(gross) else None})


def evaluate(oos, train, costs):
    edges = condition_edges(train)
    cells = decompose(oos, edges, costs)
    viable = [c for c in cells if int(c.get("n", 0)) >= MIN_CELL_N]
    positives = [c for c in viable if (c["net_mean_bps"] or 0.0) > 0.0]
    return {
        "train_boundaries": {k: v.tolist() for k, v in edges.items()},
        "cells": cells,
        "viable_cells": len(viable),
        "positive_fraction": float(len(positives) / len(viable)) if viable else None,
        "min_cell_n": MIN_CELL_N,
    }