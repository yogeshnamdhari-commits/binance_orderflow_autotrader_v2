"""V21 signed short-horizon move regression research.

Estimates the signed future mid-price move in bps from causal order-flow state.
This is deliberately separate from the directional classifier and is used to
test whether an economic alpha magnitude exists out of sample.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from scripts.v21_orderflow_dataset import FEATURES, HORIZONS_MS


BASELINE = [
    "spread_bps",
    "mid_return_100ms_bps",
    "mid_return_500ms_bps",
]

ORDERFLOW_CORE = [
    "queue_imbalance",
    "microprice_edge_bps",
    "ofi_100ms",
    "ofi_500ms",
    "ofi_1000ms",
    "trade_imbalance_100ms",
    "trade_imbalance_500ms",
    "trade_imbalance_1000ms",
    "trade_intensity_notional_s",
    "depth_5_imbalance",
]

FULL = FEATURES


def _fit(features: list[str], x: pd.DataFrame, y: pd.Series) -> Pipeline:
    model = Pipeline(
        [
            ("scale", StandardScaler()),
            ("ridge", Ridge(alpha=1.0)),
        ]
    )
    model.fit(x[features], y)
    return model


def _metrics(y: pd.Series, pred: np.ndarray) -> dict[str, float]:
    yv = y.to_numpy(dtype=float)
    pv = np.asarray(pred, dtype=float)
    corr = float(np.corrcoef(yv, pv)[0, 1]) if len(yv) > 1 and np.std(pv) > 0 else 0.0
    sign_acc = float(np.mean(np.sign(yv) == np.sign(pv)))
    return {
        "mae_bps": float(mean_absolute_error(yv, pv)),
        "rmse_bps": float(mean_squared_error(yv, pv) ** 0.5),
        "r2": float(r2_score(yv, pv)),
        "pearson_corr": corr,
        "sign_accuracy": sign_acc,
    }


def run(path: Path) -> dict[str, Any]:
    df = pd.read_parquet(path)
    sessions = sorted(df["session"].unique())
    out: dict[str, Any] = {
        "dataset_rows": int(len(df)),
        "folds": {},
        "feature_sets": {
            "baseline": BASELINE,
            "orderflow_core": ORDERFLOW_CORE,
            "full": FULL,
        },
    }

    for horizon in HORIZONS_MS:
        target = (
            (df[f"future_mid_{horizon}ms"] - df["mid"])
            * 10_000.0
            / df["mid"]
        )
        work = df.copy()
        work["target_move_bps"] = target
        work = work.replace([np.inf, -np.inf], np.nan).dropna(
            subset=["target_move_bps", *FEATURES, "timestamp_ms", "split_start_ms"]
        )

        out["folds"][str(horizon)] = {}
        for i in range(1, len(sessions)):
            test_session = sessions[i]
            prior = sessions[:i]
            train = work[work["session"].isin(prior) & (work["half"] == 0)].copy()
            test = work[(work["session"] == test_session) & (work["half"] == 1)].copy()

            train = train[
                train["timestamp_ms"] <= train["split_start_ms"] - max(HORIZONS_MS)
            ]
            if len(train) < 100 or len(test) < 50:
                out["folds"][str(horizon)][test_session] = {
                    "status": "INSUFFICIENT_DATA",
                    "train_rows": int(len(train)),
                    "test_rows": int(len(test)),
                }
                continue

            results: dict[str, Any] = {}
            zero_pred = np.zeros(len(test))
            results["zero"] = _metrics(test["target_move_bps"], zero_pred)

            for name, features in (
                ("baseline", BASELINE),
                ("orderflow_core", ORDERFLOW_CORE),
                ("full", FULL),
            ):
                model = _fit(features, train, train["target_move_bps"])
                pred = model.predict(test[features])
                results[name] = _metrics(test["target_move_bps"], pred)

            out["folds"][str(horizon)][test_session] = {
                "status": "OK",
                "train_rows": int(len(train)),
                "test_rows": int(len(test)),
                "results": results,
            }

    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.dataset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
