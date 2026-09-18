"""Evaluate the V21 two-stage order-flow model with forward OOS splits.

Stage 1 predicts whether a meaningful mid-price move will occur.
Stage 2 predicts direction conditional on a move.
No validation observations are used during model fitting.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from scripts.v21_orderflow_dataset import FEATURES, HORIZONS_MS


def _safe_auc(y: pd.Series, p: np.ndarray) -> float | None:
    if y.nunique() < 2:
        return None
    return float(roc_auc_score(y, p))


def _fit_model(x: pd.DataFrame, y: pd.Series) -> Pipeline:
    model = Pipeline(
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
    model.fit(x, y)
    return model


def _clean(frame: pd.DataFrame, horizon: int) -> pd.DataFrame:
    cols = FEATURES + [f"move_{horizon}ms", f"direction_{horizon}ms"]
    out = frame[["timestamp_ms", "session", "half", "split_start_ms", *cols]].copy()
    out = out.replace([np.inf, -np.inf], np.nan).dropna(subset=cols)
    return out


def _evaluate_fold(
    train: pd.DataFrame,
    test: pd.DataFrame,
    horizon: int,
) -> dict[str, Any]:
    train = _clean(train, horizon)
    test = _clean(test, horizon)
    # Purge the final max-horizon observations of the training half so no
    # training label can reach into the untouched validation half.
    train = train[train["timestamp_ms"] <= (train["split_start_ms"] - max(HORIZONS_MS))]
    if len(train) < 100 or len(test) < 50:
        return {
            "status": "INSUFFICIENT_DATA",
            "train_rows": len(train),
            "test_rows": len(test),
        }

    x_train = train[FEATURES]
    x_test = test[FEATURES]

    y_move_train = train[f"move_{horizon}ms"].astype(int)
    y_move_test = test[f"move_{horizon}ms"].astype(int)

    stage1 = _fit_model(x_train, y_move_train)
    p_move = stage1.predict_proba(x_test)[:, 1]

    move_metrics = {
        "auc": _safe_auc(y_move_test, p_move),
        "log_loss": float(log_loss(y_move_test, p_move, labels=[0, 1])),
        "brier": float(brier_score_loss(y_move_test, p_move)),
        "accuracy_at_0_5": float(accuracy_score(y_move_test, p_move >= 0.5)),
        "positive_rate": float(y_move_test.mean()),
    }

    move_train_mask = y_move_train == 1
    move_test_mask = y_move_test == 1
    stage2_result: dict[str, Any]

    if move_train_mask.sum() < 50 or move_test_mask.sum() < 20:
        stage2_result = {
            "status": "INSUFFICIENT_MOVE_SAMPLES",
            "train_move_rows": int(move_train_mask.sum()),
            "test_move_rows": int(move_test_mask.sum()),
        }
    else:
        y_dir_train = train.loc[move_train_mask, f"direction_{horizon}ms"].astype(int)
        y_dir_test = test.loc[move_test_mask, f"direction_{horizon}ms"].astype(int)
        stage2 = _fit_model(train.loc[move_train_mask, FEATURES], y_dir_train)
        p_up = stage2.predict_proba(test.loc[move_test_mask, FEATURES])[:, 1]
        stage2_result = {
            "status": "OK",
            "auc": _safe_auc(y_dir_test, p_up),
            "accuracy": float(accuracy_score(y_dir_test, p_up >= 0.5)),
            "log_loss": float(log_loss(y_dir_test, p_up, labels=[0, 1])),
            "up_rate": float(y_dir_test.mean()),
            "samples": int(len(y_dir_test)),
        }

    return {
        "status": "OK",
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "train_move_rate": float(y_move_train.mean()),
        "test_move_rate": float(y_move_test.mean()),
        "stage1": move_metrics,
        "stage2": stage2_result,
    }


def _forward_splits(df: pd.DataFrame) -> list[tuple[str, pd.DataFrame, pd.DataFrame]]:
    sessions = sorted(df["session"].unique())
    folds: list[tuple[str, pd.DataFrame, pd.DataFrame]] = []
    for i in range(1, len(sessions)):
        test_session = sessions[i]
        prior = sessions[:i]
        train = df[df["session"].isin(prior) & (df["half"] == 0)]
        test = df[(df["session"] == test_session) & (df["half"] == 1)]
        folds.append((test_session, train, test))
    return folds


def _model_summary(model: Pipeline) -> dict[str, Any]:
    logit = model.named_steps["logit"]
    scaler = model.named_steps["scale"]
    return {
        "coefficients_scaled": [float(x) for x in logit.coef_[0]],
        "intercept": float(logit.intercept_[0]),
        "feature_order": FEATURES,
        "training_feature_mean": [float(x) for x in scaler.mean_],
        "training_feature_scale": [float(x) for x in scaler.scale_],
    }


def run(path: Path) -> dict[str, Any]:
    df = pd.read_parquet(path)
    report: dict[str, Any] = {
        "dataset_rows": int(len(df)),
        "sessions": sorted(df["session"].unique().tolist()),
        "features": FEATURES,
        "horizons_ms": list(HORIZONS_MS),
        "protocol": "forward_oos: train on earlier session first halves, test on later session second halves",
        "folds": {},
    }

    for horizon in HORIZONS_MS:
        report["folds"][str(horizon)] = {}
        for session, train, test in _forward_splits(df):
            result = _evaluate_fold(train, test, horizon)
            report["folds"][str(horizon)][session] = result

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
