"""V3 predictive model — regularized linear prediction of expected forward move.

Primary V3 model (research-backed, not a black box): a closed-form ridge OLS on
z-scored features, fit ONCE on the predeclared chronological TRAINING slice,
per predeclared horizon. The expected move E[r_h | X] (continuous, magnitude
target) feeds the execution-aware economic gate; the sign of the move
determines LONG vs SHORT. Coefficients and standardization statistics are
frozen to v3_model.json before any OOS evaluation.

No grid search, no indicator mining, no selection on validation/OOS.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .v3_features import MODEL_FEATURES, PREDECLARED_HORIZONS_MS
from .v3_labels import add_labels

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


def fit_horizon(Xtr, ytr, alpha=RIDGE_ALPHA):
    mus = np.nanmean(Xtr, axis=0)
    sds = np.nanstd(Xtr, axis=0)
    sds = np.where(sds < 1e-12, 1.0, sds)
    Z = (Xtr - mus) / sds
    ok = np.isfinite(Z).all(axis=1) & np.isfinite(ytr)
    if ok.sum() < 200:
        raise ValueError("insufficient train rows (need >=200, got %d)"
                         % int(ok.sum()))
    A = Z[ok].T @ Z[ok] + alpha * np.eye(Z.shape[1])
    b = Z[ok].T @ ytr[ok]
    beta = np.linalg.solve(A, b)
    b0 = float(ytr[ok].mean() - beta @ np.nanmean(Z[ok], axis=0))
    pred = b0 + Z[ok] @ beta
    resid = ytr[ok] - pred
    sst = np.sum((ytr[ok] - ytr[ok].mean()) ** 2)
    r2 = 1.0 - np.sum(resid ** 2) / sst if sst else 0.0
    return beta, b0, mus, sds, float(r2), int(ok.sum())


def calibrate(feature_path, out_dir, horizons=PREDECLARED_HORIZONS_MS):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    df = add_labels(pd.read_parquet(feature_path), horizons)
    splits = chrono_split_masks(df)
    train = df.loc[splits[0]["mask"]]

    cuts = {}
    for s in splits:
        cuts[s["name"]] = {"lo_ms": int(df.loc[s["mask"], "ts_ms"].min()),
                           "hi_ms": int(df.loc[s["mask"], "ts_ms"].max()),
                           "rows": int(s["mask"].sum())}

    model = {"generated_at": datetime.now(timezone.utc).isoformat(),
             "alpha": RIDGE_ALPHA, "features": MODEL_FEATURES,
             "label_horizons_ms": list(horizons),
             "split_fractions": list(SPLIT_FRACTIONS), "splits": cuts}

    calib = {"features": MODEL_FEATURES, "horizons": list(horizons)}
    Xtr = train[MODEL_FEATURES].to_numpy(float)
    for h in horizons:
        ytr = train["r_%d" % h].to_numpy(float)
        beta, b0, mu, sd, r2, n = fit_horizon(Xtr, ytr)
        model[str(h)] = {"coef": [float(x) for x in beta], "intercept": float(b0),
                         "mean": [float(x) for x in mu],
                         "std": [float(x) for x in sd],
                         "r2_train": r2, "n_train": n}
        calib[str(h)] = {"r2_train": r2, "n_train": n}
    (out_dir / "v3_model.json").write_text(json.dumps(model, indent=1))
    (out_dir / "v3_calibration.json").write_text(json.dumps(calib, indent=1))
    return model, calib


def load_model(path):
    return json.load(open(path))


def predict(model_d, df, horizon_ms):
    d = model_d[str(horizon_ms)]
    X = df[MODEL_FEATURES].to_numpy(float) if isinstance(df, pd.DataFrame) \
        else df
    mu = np.array(d["mean"])
    sd = np.array(d["std"])
    Z = (X - mu) / sd
    Zt = np.where(np.isfinite(Z), Z, 0.0)
    return d["intercept"] + Zt @ np.array(d["coef"])


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", type=Path,
                    default=Path("data/research/v3_features.parquet"))
    ap.add_argument("--out", type=Path, default=Path("data/research"))
    a = ap.parse_args()
    m, c = calibrate(a.features, a.out)
    print("r2 per horizon:", {k: round(v["r2_train"], 4)
                              for k, v in c.items()})