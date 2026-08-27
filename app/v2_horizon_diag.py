"""V2 predeclared-horizon diagnostic — research only; DOES NOT alter trading logic.

Question, declared BEFORE any profitability is examined:

  Does Binance BTCUSDT L2 order-flow information carry economically meaningful
  forward impact at predeclared horizons?

Predeclared horizons (locked before computation, no post-hoc selection):
  _FROZEN_HORIZONS   (250, 500, 1000)  the horizons already fixed in the frozen
                          model (label engine LABEL_HORIZONS_MS). Forecasts at
                          these horizons use the FROZEN coefficients verbatim.
  _DECLARED_HORIZONS (250, 500, 1000, 2000, 5000)
                          longer forward horizons at which OFI impact may
                          develop (recent OFI studies measure impact over
                          minutes, not one 500 ms interval). For 2000/5000 the
                          SAME linear ridge procedure is re-estimated on the
                          TRAIN slice only as a declared diagnostic projection;
                          the trading model is never extended or changed.

No thresholds, weights, TP/SL, signal, or cost changes. For every horizon this
module reports diagnostics only:
  1. realized-move magnitude (mean |r_h|, std) vs measured cost  -> the
     "horizon too short" test: if mean |r_h| < cost, no direction model can win
  2. forecast magnitude distribution and IC (Pearson + Spearman rank)
  3. OOS gross expectancy and net expectancy after measured costs
  4. univariate predictive coefficient (bps per std) of NFI and normalized OFI
  5. conditional relationships: mean realized forward move and mean forecast by
     TRAIN-defined terciles of core order-flow features (NFI, trade flow, QI,
     depth, spread, absorption/event rate, microprice deviation)
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .v2_cost_gate import taker_cost_bps, maker_cost_bps
from .v2_labels import add_labels
from .v2_model import MODEL_FEATURES, load_model, predict, _zscore_fit, ridge_ols

FROZEN_HORIZONS = (250, 500, 1000)
DECLARED_HORIZONS = (250, 500, 1000, 2000, 5000)
FEATURE_DIAG = ["nofi_1", "nofi_5", "tfi_500", "qi1", "qi10", "log_depth10",
                "spread_bps", "log_event_rate", "mpd_bps"]
ALPHA = 0.05


def _diag_forecast(model_d, df, h, train_n):
    """Frozen-coefficient forecast if h in the model, else a train-projection
    using the identical ridge procedure (train slice only)."""
    if str(h) in model_d:
        return predict(model_d, df, h), None
    Xtr = df[MODEL_FEATURES].to_numpy(float)[:train_n]
    Ztr, mu, sd = _zscore_fit(Xtr)
    ytr = df["r_%d" % h].to_numpy(float)[:train_n]
    ok = np.isfinite(Ztr).all(axis=1) & np.isfinite(ytr)
    beta, b0, r2 = ridge_ols(Ztr[ok], ytr[ok], alpha=ALPHA)
    Zo = (df[MODEL_FEATURES].to_numpy(float) - mu) / sd
    return b0 + Zo @ beta, {"beta": [float(x) for x in beta], "b0": float(b0),
                            "r2_train": float(r2), "n_train": int(ok.sum())}


def _tercile_edges(x):
    q = np.nanpercentile(np.asarray(x, dtype=float), [33.33, 66.67])
    return np.array([-np.inf, q[0], q[1], np.inf])


def _conditional(oos, train, feature, label, fore):
    edges = _tercile_edges(np.asarray(train[feature], dtype=float))
    q = np.asarray(oos[feature], dtype=float)
    rows = []
    for b in range(len(edges) - 1):
        m = (q >= edges[b]) & (q < edges[b + 1]) & np.isfinite(q) & \
            np.isfinite(label) & np.isfinite(fore)
        if not m.any():
            rows.append({"feature": feature, "tercile": b, "n": 0})
            continue
        rows.append({"feature": feature, "tercile": b, "n": int(m.sum()),
                     "mean_realized_bps": float(np.mean(label[m])),
                     "mean_forecast_bps": float(np.mean(fore[m]))})
    return rows


def _directions(label, fore, cost_bps):
    label = np.asarray(label, dtype=float)
    fore = np.asarray(fore, dtype=float)
    long_m = (fore > 0) & np.isfinite(label)
    short_m = (fore < 0) & np.isfinite(label)
    out = {}
    for name, m in (("long", long_m), ("short", short_m)):
        if not m.any():
            out[name] = {"n": 0}
            continue
        net = label[m] - cost_bps if name == "long" else -label[m] - cost_bps
        out[name] = {"n": int(m.sum()),
                     "gross_mean_bps": float(np.mean(label[m] if name == "long"
                                                     else -label[m])),
                     "net_mean_bps": float(np.mean(net)),
                     "hit_rate": float((net > 0).mean())}
    return out


def horizon_report(model_d, df, h, train_n, cal, notional_usd):
    fore, proj = _diag_forecast(model_d, df, h, train_n)
    label = df["r_%d" % h].to_numpy(float)
    tr = df.iloc[:train_n]
    oos = df.iloc[train_n:]
    o, f = label[train_n:], fore[train_n:]
    fin = np.isfinite(o) & np.isfinite(f)
    lo, lf = o[fin], f[fin]
    n = int(fin.sum())
    ic_pearson = float(np.corrcoef(lf, lo)[0, 1]) if n >= 2 else None
    _sr = _spearman(lf, lo) if n >= 2 else None

    cost_tak = taker_cost_bps(cal, notional_usd)
    cost_mak, mak_comp = maker_cost_bps(cal)

    cond = []
    for feat in FEATURE_DIAG:
        cond.extend(_conditional(oos, tr, feat, o, f))

    uni = {}
    for feat in ("nofi_1", "tfi_500", "qi1"):
        xa = np.asarray(tr[feat], dtype=float)
        yo = np.asarray(tr["r_%d" % h], dtype=float)
        ok = np.isfinite(xa) & np.isfinite(yo)
        if ok.sum() >= 30 and np.std(xa[ok]) > 1e-12:
            xm, xs = xa[ok].mean(), np.std(xa[ok])
            beta = np.polyfit((xa[ok] - xm) / xs, yo[ok], 1)[0]
            uni[feat] = {"coef_bps_per_std": float(beta), "n": int(ok.sum())}
        else:
            uni[feat] = None

    return {
        "horizon_ms": h,
        "oos_n": n,
        "frozen_or_projection": "frozen" if str(h) in model_d else "train_projection",
        "projection": proj,
        "costs_bps": {"taker_rt": cost_tak, "maker_rt": cost_mak},
        "realized_move": {"mean_abs_bps": float(np.mean(np.abs(lo))),
                          "std_bps": float(np.std(lo)),
                          "mean_bps": float(np.mean(lo)),
                          "p1_bps": float(np.percentile(lo, 1)),
                          "p99_bps": float(np.percentile(lo, 99))},
        "forecast": {"mean_bps": float(np.mean(lf)),
                     "std_bps": float(np.std(lf)),
                     "abs_p50_bps": float(np.percentile(np.abs(lf), 50)),
                     "abs_p90_bps": float(np.percentile(np.abs(lf), 90)),
                     "abs_p99_bps": float(np.percentile(np.abs(lf), 99)),
                     "max_abs_bps": float(np.max(np.abs(lf))),
                     "corr_pearson": ic_pearson, "corr_spearman": _sr},
        "gross_expectancy_bps": float(np.mean(lo * np.sign(lf))),
        "net_expectancy": _directions(lo, lf, cost_tak),
        "univariate_coef": uni,
        "conditional": cond,
        "interpretation": ("dead_on_arrival" if np.mean(np.abs(lo)) < cost_tak
                           else "move_clears_taker_cost"),
    }


def _spearman(x, y):
    r = np.argsort(np.argsort(x))
    s = np.argsort(np.argsort(y))
    return float(np.corrcoef(r, s)[0, 1])


def build_diag(args, model_d, df):
    train_n = int((df["ts_ms"] <= int(model_d["splits"]["train"]["hi_ms"])).sum())
    cal = json.load(open(args.cost_cal))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "question": ("Does Binance L2 BTCUSDT order-flow information carry "
                     "economically meaningful forward impact at predeclared "
                     "horizons?"),
        "declared_horizons": list(DECLARED_HORIZONS),
        "frozen_horizons": list(FROZEN_HORIZONS),
        "train_n": train_n, "total_rows": len(df),
        "note": ("no trading parameter was changed; horizons beyond the frozen "
                 "set are evaluated with the identical ridge procedure on the "
                 "train slice only (declared diagnostic projection)"),
        "horizons": [horizon_report(model_d, df, h, train_n, cal,
                                    args.notional_usd)
                     for h in args.horizons],
    }


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", type=Path,
                    default=Path("data/hist/research/v2_features.parquet"))
    ap.add_argument("--model", type=Path,
                    default=Path("data/hist/research/v2_model.json"))
    ap.add_argument("--cost-cal", type=Path,
                    default=Path("data/hist/research/execution_calibration.json"))
    ap.add_argument("--horizons", default=",".join(map(str, DECLARED_HORIZONS)))
    ap.add_argument("--notional-usd", type=float, default=1000.0)
    ap.add_argument("--out", type=Path,
                    default=Path("data/hist/research/V2_HORIZON_DIAG.json"))
    a = ap.parse_args()

    df = add_labels(pd.read_parquet(a.features),
                    horizons=tuple(int(x) for x in a.horizons.split(",")))
    a.horizons = tuple(int(x) for x in a.horizons.split(","))
    model_d = load_model(a.model)
    diag = build_diag(a, model_d, df)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(diag, indent=1, default=str))
    print("wrote", a.out)
    for h in diag["horizons"]:
        print("H=%4dms  |r|mean=%6.3f std=%6.3f bps | fore std=%6.3f bps | "
              "IC p/r=%.3f/%.3f | gross=%+.4f bps | net(taker)=%.3f bps | %s"
              % (h["horizon_ms"], h["realized_move"]["mean_abs_bps"],
                 h["realized_move"]["std_bps"], h["forecast"]["std_bps"],
                 h["forecast"]["corr_pearson"] or 0.0,
                 h["forecast"]["corr_spearman"] or 0.0,
                 h["gross_expectancy_bps"],
                 h["net_expectancy"]["long"]["net_mean_bps"]
                 if h["net_expectancy"]["long"].get("net_mean_bps") is not None
                 else 0.0,
                 h["interpretation"]))


if __name__ == "__main__":
    main()