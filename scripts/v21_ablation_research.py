"""V21 ablation research: test whether order-flow features add information
beyond simple recent-return/spread baselines.

Research only. This produces incremental evidence and does not certify a strategy.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score
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


def _model(x: pd.DataFrame, y: pd.Series) -> Pipeline:
    m = Pipeline(
        [
            ("scale", StandardScaler()),
            (
                "logit",
                LogisticRegression(
                    C=1.0,
                    max_iter=2000,
                    class_weight="balanced",
                    solver="lbfgs",
                    random_state=0,
                ),
            ),
        ]
    )
    m.fit(x, y)
    return m


def _clean(df: pd.DataFrame, horizon: int, target: str) -> pd.DataFrame:
    cols = ["timestamp_ms", "split_start_ms", *FEATURES, target]
    out = df[cols].replace([np.inf, -np.inf], np.nan).dropna()
    # Prevent a training label from looking beyond the first-half/second-half split.
    out = out[out["timestamp_ms"] <= out["split_start_ms"] - max(HORIZONS_MS)]
    return out


def _eval_feature_set(
    train: pd.DataFrame,
    test: pd.DataFrame,
    features: list[str],
    target: str,
) -> dict[str, Any]:
    if len(train) < 100 or len(test) < 50:
        return {"status": "INSUFFICIENT_DATA", "train_rows": len(train), "test_rows": len(test)}
    y_train = train[target].astype(int)
    y_test = test[target].astype(int)
    if y_train.nunique() < 2 or y_test.nunique() < 2:
        return {"status": "INSUFFICIENT_CLASSES", "train_rows": len(train), "test_rows": len(test)}

    model = _model(train[features], y_train)
    p = model.predict_proba(test[features])[:, 1]
    return {
        "status": "OK",
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "auc": float(roc_auc_score(y_test, p)),
        "log_loss": float(log_loss(y_test, p, labels=[0, 1])),
    }


def run(path: Path) -> dict[str, Any]:
    df = pd.read_parquet(path)
    sessions = sorted(df["session"].unique())
    report: dict[str, Any] = {
        "dataset_rows": int(len(df)),
        "features": {
            "baseline": BASELINE,
            "orderflow_core": ORDERFLOW_CORE,
            "full": FULL,
        },
        "folds": {},
    }

    for horizon in HORIZONS_MS:
        hz = str(horizon)
        report["folds"][hz] = {}
        target_move = f"move_{horizon}ms"
        target_direction = f"direction_{horizon}ms"

        for i in range(1, len(sessions)):
            test_session = sessions[i]
            prior = sessions[:i]
            train_base = df[df["session"].isin(prior) & (df["half"] == 0)]
            test_base = df[(df["session"] == test_session) & (df["half"] == 1)]

            train_move = _clean(train_base, horizon, target_move)
            test_move = test_base[
                ["timestamp_ms", "split_start_ms", *FEATURES, target_move]
            ].replace([np.inf, -np.inf], np.nan).dropna()

            move_results = {
                "baseline": _eval_feature_set(train_move, test_move, BASELINE, target_move),
                "orderflow_core": _eval_feature_set(train_move, test_move, ORDERFLOW_CORE, target_move),
                "full": _eval_feature_set(train_move, test_move, FULL, target_move),
            }

            train_dir = _clean(train_base[train_base[target_move] == 1], horizon, target_direction)
            test_dir = test_base[test_base[target_move] == 1][
                ["timestamp_ms", "split_start_ms", *FEATURES, target_direction]
            ].replace([np.inf, -np.inf], np.nan).dropna()

            direction_results = {
                "baseline": _eval_feature_set(train_dir, test_dir, BASELINE, target_direction),
                "orderflow_core": _eval_feature_set(train_dir, test_dir, ORDERFLOW_CORE, target_direction),
                "full": _eval_feature_set(train_dir, test_dir, FULL, target_direction),
            }

            def delta(a: dict[str, Any], b: dict[str, Any]) -> dict[str, float | None]:
                if a.get("status") != "OK" or b.get("status") != "OK":
                    return {"auc": None, "log_loss": None}
                return {
                    "auc": float(a["auc"] - b["auc"]),
                    "log_loss": float(a["log_loss"] - b["log_loss"]),
                }

            report["folds"][hz][test_session] = {
                "move": move_results,
                "move_incremental_full_vs_baseline": delta(move_results["full"], move_results["baseline"]),
                "move_incremental_orderflow_vs_baseline": delta(move_results["orderflow_core"], move_results["baseline"]),
                "direction": direction_results,
                "direction_incremental_full_vs_baseline": delta(direction_results["full"], direction_results["baseline"]),
                "direction_incremental_orderflow_vs_baseline": delta(direction_results["orderflow_core"], direction_results["baseline"]),
            }

    return report


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
