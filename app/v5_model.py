"""V5 model — frozen short-horizon expected-move ridge (closed-form, predeclared).

E[ΔP_h | X] = intercept + beta . z(X), z standardized with train-slice mu/sd;
fit ONCE on the chronological TRAIN slice only (SPLIT_FRACTIONS 70/15/15 by
timestamp quantile, identical convention to V3). Coefficients are frozen to
v5_model.json before any OOS evaluation. The sign of the expected move selects
LONG/SHORT; its magnitude feeds the measured-cost gate (v5_cost).

Reuses the verified ridge estimator from v3_model but binds its feature list
to V5_FEATURES (saved in the model record so predict() needs no globals).
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .v3_labels import add_labels
from .v3_model import fit_horizon, chrono_split_masks, SPLIT_FRACTIONS
from .v5_features import V5_FEATURES, HORIZONS_MS

RIDGE_ALPHA = 0.05
PRIMARY_HORIZON = 500


def calibrate(feature_path, out_dir, horizons=HORIZONS_MS):
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
             "alpha": RIDGE_ALPHA, "features": V5_FEATURES,
             "label_horizons_ms": list(horizons),
             "primary_horizon_ms": PRIMARY_HORIZON,
             "split_fractions": list(SPLIT_FRACTIONS), "splits": cuts}
    calib = {"features": V5_FEATURES, "horizons": list(horizons)}
    Xtr = train[V5_FEATURES].to_numpy(float)
    for h in horizons:
        ytr = train["r_%d" % h].to_numpy(float)
        beta, b0, mu, sd, r2, n = fit_horizon(Xtr, ytr, alpha=RIDGE_ALPHA)
        model[str(h)] = {"coef": [float(x) for x in beta],
                         "intercept": float(b0),
                         "mean": [float(x) for x in mu],
                         "std": [float(x) for x in sd],
                         "r2_train": r2, "n_train": n}
        calib[str(h)] = {"r2_train": r2, "n_train": n}
    (out_dir / "v5_model.json").write_text(json.dumps(model, indent=1))
    (out_dir / "v5_calibration.json").write_text(json.dumps(calib, indent=1))
    return model, calib


def load_model(path):
    return json.load(open(path))


def predict(model_d, df, horizon_ms=PRIMARY_HORIZON):
    import numpy as np
    d = model_d[str(horizon_ms)]
    X = df[model_d["features"]] if hasattr(df, "columns") else df
    Z = (X.to_numpy(float) - np.array(d["mean"])) / np.array(d["std"])
    Z = np.where(np.isfinite(Z), Z, 0.0)
    return d["intercept"] + Z @ np.array(d["coef"])