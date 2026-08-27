"""V2 Phase-3 calibration (parsimonious linear model, frozen after training).

Estimates, once, on the predeclared TRAINING slice only:

  E[r_{t+h}] = b0 + sum_k b_k * X_k(t)      for h in LABEL_HORIZONS_MS

using closed-form ridge regression (alpha=0.05) on z-scored features
(mean/std estimated on training). Coefficients, standardization statistics,
alpha, the chronological split boundaries and feature set are written to
v2_model.json and are IMMUTABLE afterwards (Phase 4 freeze). The VALIDATION
slice is never touched here.

X(t) is the frozen model feature set (see v2_features.MODEL_FEATURES):
  NOFI_1/5/10, TFI@500, QI_1/5/10, MPD, spread_bps, log(depth10), log(event_rate)

Also writes v2_calibration.json with per-feature univariate estimates and
combined train R^2 per horizon. No indicator mining, no grid search, no
selection on validation/OOS.
"""

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .v2_features import LABEL_HORIZONS_MS, MODEL_FEATURES
from .v2_labels import add_labels

RIDGE_ALPHA = 0.05
SPLIT_FRACTIONS = (0.70, 0.15, 0.15)  # train / validation / OOS (chronological)


def chrono_split_masks(df):
    ts = df["ts_ms"].to_numpy(dtype=np.int64)
    lo, mid, hi = SPLIT_FRACTIONS
    cut1 = np.quantile(ts, lo)
    cut2 = np.quantile(ts, lo + mid)
    return ({'name': 'train', 'mask': ts <= cut1},
            {'name': 'validation', 'mask': (ts > cut1) & (ts <= cut2)},
            {'name': 'oos', 'mask': ts > cut2})


def _zscore_fit(X):
    X = X.astype(float, copy=False)
    mu = np.nanmean(X, axis=0)
    sd = np.nanstd(X, axis=0)
    sd = np.where(sd < 1e-12, 1.0, sd)
    Z = (X - mu) / sd
    return Z, mu, sd


def ridge_ols(Z, y, alpha=RIDGE_ALPHA):
    n, k = Z.shape
    A = Z.T @ Z + alpha * np.eye(k)
    b = Z.T @ y
    beta = np.linalg.solve(A, b)
    b0 = float(y.mean() - beta @ Z.mean(axis=0))
    resid = y - (b0 + Z @ beta)
    sst = np.sum((y - y.mean()) ** 2)
    r2 = 1.0 - np.sum(resid ** 2) / sst if sst else 0.0
    return beta, b0, float(r2)


def _univariate(frame, feature, horizon):
    y = frame["r_%d" % horizon].to_numpy(float)
    x = frame[feature].to_numpy(float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if len(x) < 30 or np.std(x) < 1e-12:
        return {"feature": feature, "horizon_ms": horizon, "n": int(len(x)),
                "coef_bps": None, "r2": None}
    xm, xsd = x.mean(), np.std(x)
    z = (x - xm) / xsd
    beta, b0, r2 = ridge_ols(z[:, None], y, alpha=0.01)
    return {"feature": feature, "horizon_ms": horizon, "n": int(len(x)),
            "coef_std": float(beta[0]),
            "coef_bps": float(beta[0] / xsd), "intercept_bps": float(b0), "r2": float(r2)}


def calibrate(feature_path, out_dir, horizon_ms=LABEL_HORIZONS_MS,
              saver=lambda d, p: Path(p).write_text(json.dumps(d, indent=1, default=str))):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet(feature_path)
    df = add_labels(df, horizons=horizon_ms)
    splits = chrono_split_masks(df)
    train = df.loc[splits[0]["mask"]]

    cuts = {}
    for s in splits:
        cuts[s["name"]] = {
            "lo_ms": int(df.loc[s["mask"], "ts_ms"].min()),
            "hi_ms": int(df.loc[s["mask"], "ts_ms"].max()),
            "rows": int(s["mask"].sum()),
        }

    model_block = {"frozen_at": __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).isoformat(),
        "alpha": RIDGE_ALPHA, "features": MODEL_FEATURES,
        "tfi_horizon_ms": 500, "label_horizons_ms": list(horizon_ms),
        "split_fractions": list(SPLIT_FRACTIONS), "splits": cuts}

    calibration = {"model_features": MODEL_FEATURES,
                   "label_horizons_ms": list(horizon_ms), "alpha": RIDGE_ALPHA,
                   "univariate": [], "combined_train": {}}

    X = train[MODEL_FEATURES].to_numpy(float)
    Z, mu, sd = _zscore_fit(X)
    for h in horizon_ms:
        y = train["r_%d" % h].to_numpy(float)
        ok = np.isfinite(Z).all(axis=1) & np.isfinite(y)
        if ok.sum() < 200:
            raise ValueError("insufficient train rows (need >=200, got %d)" % int(ok.sum()))
        beta, b0, r2 = ridge_ols(Z[ok], y[ok])
        model_block[str(h)] = {
            "coef": [float(x) for x in beta], "intercept": float(b0),
            "mean": [float(x) for x in mu], "std": [float(x) for x in sd],
            "r2_train": float(r2), "n_train": int(ok.sum())}
        for f in MODEL_FEATURES:
            calibration["univariate"].append(_univariate(train, f, h))
        calibration["combined_train"][str(h)] = {"r2": float(r2), "n": int(ok.sum())}

    model_path = out_dir / "v2_model.json"
    calib_path = out_dir / "v2_calibration.json"
    saver(model_block, model_path)
    saver(calibration, calib_path)
    return model_block, calibration


def load_model(path):
    return json.load(open(path))


def predict(model_block, df, horizon_ms):
    d = model_block[str(horizon_ms)]
    X = df[MODEL_FEATURES].to_numpy(float)
    mu = np.array(d["mean"])
    sd = np.array(d["std"])
    beta = np.array(d["coef"])
    Z = (X - mu) / sd
    return d["intercept"] + Z @ beta


def frozen_predict(model_path, df, horizon_ms):
    return predict(load_model(model_path), df, horizon_ms)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", type=Path, default=Path("data/hist/research/v2_features.parquet"))
    ap.add_argument("--out", type=Path, default=Path("data/hist/research"))
    a = ap.parse_args()
    m, c = calibrate(a.features, a.out)
    print(json.dumps(c["combined_train"], indent=1))