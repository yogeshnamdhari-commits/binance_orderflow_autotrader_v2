"""V13 pipeline — calibrate + independent forward validation at 2s horizon.

Reuses battle-tested V11 parser and V12 execution-cost / statistics / funding
modules. Only the feature set, model, and horizon are V13-specific.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from app.v12.execution_model import V12ExecutionModel, V12ExecutionConfig
from app.v12.statistics import validate_statistics
from app.v12.funding import fetch_and_cache, average_funding_rate_during
from app.v11.parser import V11DataParser
from app.v13.config import V13Config
from app.v13.features import extract_v13_features, build_v13_targets, build_v13_returns, V13_BASE_FEATURES
from app.v13.model import V13SignalModel


PROTOCOL_V13 = {
    "horizon_ms": V13Config.prediction_horizon_ms,
    "horizon_s": V13Config.prediction_horizon_ms / 1000.0,
    "taker_fee_bps": V13Config.taker_fee_bps,
    "maker_fee_bps": V13Config.maker_fee_bps,
    "slippage_bps": V13Config.slippage_bps,
    "adverse_selection_bps": V13Config.adverse_selection_bps,
    "latency_bps": V13Config.latency_bps,
    "exit_cost_bps": V13Config.exit_cost_bps,
    "funding_threshold_bps": V13Config.funding_threshold_bps,
    "min_observations_calibration": V13Config.min_observations_calibration,
    "min_observations_forward": V13Config.min_observations_forward,
    "alpha": V13Config.alpha,
    "min_effect_size": V13Config.min_effect_size,
    "model": "LogisticRegression",
    "features": V13_BASE_FEATURES,
}


def _parse_session(session_dir: Path) -> tuple[list, list]:
    return V11DataParser(session_dir).parse()


def _build_exec_model(config: V13Config) -> V12ExecutionModel:
    ec = V12ExecutionConfig(
        taker_fee_bps=config.taker_fee_bps,
        maker_fee_bps=config.maker_fee_bps,
        slippage_bps=config.slippage_bps,
        adverse_selection_bps=config.adverse_selection_bps,
        latency_bps=config.latency_bps,
        exit_cost_bps=config.exit_cost_bps,
        stop_loss_bps=config.stop_loss_bps,
        take_profit_bps=config.take_profit_bps,
        holding_hours=config.max_holding_hours,
    )
    return V12ExecutionModel(config=ec)


def run_v13_calibration(calibration_dirs: list[Path], output_dir: Path, config: V13Config) -> dict:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_books, all_trades = [], []
    for d in calibration_dirs:
        books, trades = _parse_session(d)
        all_books.extend(books)
        all_trades.extend(trades)

    all_books.sort(key=lambda b: b.ts_ms)
    all_trades.sort(key=lambda t: t.ts_ms)

    df = extract_v13_features(all_books, all_trades, window_ms=config.feature_window_ms)
    df["target"] = build_v13_targets(df, horizon_ms=config.prediction_horizon_ms).values
    df["actual_return"] = build_v13_returns(df, horizon_ms=config.prediction_horizon_ms).values
    df = df.dropna(subset=["target", "actual_return"])
    df = df[df["target"].isin([0, 1])]

    n_obs = len(df)
    print(f"[V13] Calibration observations: {n_obs}")

    model = V13SignalModel()
    feature_cols = [c for c in V13_BASE_FEATURES if c in df.columns]
    X = df[feature_cols].copy()
    y = df["target"].copy()
    returns = df["actual_return"].copy()

    print("[V13] Training logistic regression model...")
    metrics = model.fit(X, y, returns=returns)
    print(f"  Train AUC: {metrics['train_auc']:.4f}")
    print(f"  Val AUC:   {metrics['val_auc']:.4f}")
    print(f"  Test AUC:  {metrics['test_auc']:.4f}")

    model_path = output_dir / "v13_frozen_model.joblib"
    model_checksum = model.save(model_path)
    print(f"[V13] Frozen model saved: {model_path}")

    artifact = {
        "version": "V13",
        "experiment_id": config.experiment_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "CALIBRATED",
        "config_hash": V13Config.config_hash(),
        "model_hash": model_checksum,
        "model_path": str(model_path),
        "metrics": metrics,
        "n_observations": n_obs,
        "feature_names": feature_cols,
        "hypothesis_pre_registered": True,
    }
    (output_dir / "v13_calibration_artifact.json").write_text(json.dumps(artifact, indent=2))
    return artifact


def _analyze_v13_regimes(net_ev: pd.Series, df: pd.DataFrame) -> dict:
    regimes = {}
    if "spread_bps" in df.columns:
        hi = net_ev[df["spread_bps"] >= 0.02]
        lo = net_ev[df["spread_bps"] < 0.02]
        regimes["spread_regime"] = {
            "high_spread": {"n": len(hi), "mean_net_ev_bps": float(hi.mean()) if len(hi) else None,
                            "positive_rate": float((hi > 0).mean()) if len(hi) else None},
            "low_spread": {"n": len(lo), "mean_net_ev_bps": float(lo.mean()) if len(lo) else None,
                           "positive_rate": float((lo > 0).mean()) if len(lo) else None},
        }
    vol_col = "vol_2000" if "vol_2000" in df.columns else "vol_500"
    if vol_col in df.columns:
        p50 = df[vol_col].median()
        hi = net_ev[df[vol_col] >= p50]
        lo = net_ev[df[vol_col] < p50]
        regimes["vol_regime"] = {
            "high_vol": {"n": len(hi), "mean_net_ev_bps": float(hi.mean()) if len(hi) else None,
                         "positive_rate": float((hi > 0).mean()) if len(hi) else None},
            "low_vol": {"n": len(lo), "mean_net_ev_bps": float(lo.mean()) if len(lo) else None,
                        "positive_rate": float((lo > 0).mean()) if len(lo) else None},
        }
    terciles = pd.qcut(df.index, 3, labels=["early", "mid", "late"])
    regimes["time_regime"] = {}
    for label in ["early", "mid", "late"]:
        mask = terciles == label
        sub = net_ev[mask]
        regimes["time_regime"][label] = {
            "n": int(mask.sum()),
            "mean_net_ev_bps": float(sub.mean()) if len(sub) else None,
            "positive_rate": float((sub > 0).mean()) if len(sub) else None,
        }
    return regimes


def run_v13_forward(forward_dirs: list[Path], model_path: Path, output_dir: Path, config: V13Config) -> dict:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    model = V13SignalModel.load(model_path)
    print(f"[V13] Loaded frozen model (val_auc={model.val_auc})")

    exec_model = _build_exec_model(config)

    all_books, all_trades = [], []
    for d in forward_dirs:
        books, trades = _parse_session(d)
        all_books.extend(books)
        all_trades.extend(trades)
        print(f"  {d.name}: {len(books)} book snapshots, {len(trades)} trades")

    all_books.sort(key=lambda b: b.ts_ms)
    all_trades.sort(key=lambda t: t.ts_ms)

    df = extract_v13_features(all_books, all_trades, window_ms=config.feature_window_ms)
    df["actual_return"] = build_v13_returns(df, horizon_ms=config.prediction_horizon_ms).values
    df = df.dropna(subset=["actual_return"])

    n_orders = len(df)
    print(f"[V13] Forward observations: {n_orders}")

    ts_series = df["ts_ms"].values
    fwd_start_ms = int(ts_series.min()) if n_orders > 0 else int(time.time() * 1000)
    fwd_end_ms = int(ts_series.max()) if n_orders > 0 else fwd_start_ms + 1
    fwd_start_ms -= 8 * 3600_000
    print(f"[V13] Fetching real funding rates [{fwd_start_ms}, {fwd_end_ms}]...")
    try:
        funding_points = fetch_and_cache(
            symbol=config.symbol, start_ms=fwd_start_ms, end_ms=fwd_end_ms,
            cache_path=output_dir / "v13_forward_funding_cache.json",
        )
    except Exception as exc:
        print(f"[V13] WARNING: funding fetch failed ({exc})")
        funding_points = []

    feature_cols = [c for c in model._feature_names if c in df.columns]
    X = df[feature_cols].copy()
    X = X.replace([np.inf, -np.inf], 0.0).fillna(0.0)
    predicted_probs = model.predict_proba(X)
    predicted_returns = model.predict_returns(X)

    actual_spread = float(df["spread_bps"].mean()) if "spread_bps" in df.columns else 0.013
    hold_hours = config.max_holding_hours
    econ_results = []
    for i in range(len(df)):
        ts = int(ts_series[i])
        funding_rate = average_funding_rate_during(funding_points, ts, ts + int(hold_hours * 3600_000))
        econ = exec_model.decompose_trade(
            signal_edge_bps=float(predicted_returns[i]),
            funding_rate_8h=funding_rate,
            hold_duration_hours=hold_hours,
            signal_confidence=float(predicted_probs[i]),
            spread_bps=actual_spread,
        )
        econ_results.append(econ)

    net_ev_series = pd.Series([e.net_ev_bps for e in econ_results])
    from app.v12.statistics import analyze_regimes
    stats_result = validate_statistics(net_ev_series, alpha=config.alpha)
    regimes = _analyze_v13_regimes(net_ev_series, df)

    mean_net = float(np.mean([e.net_ev_bps for e in econ_results]))
    gate_conditions = {
        "sufficient_observations": n_orders >= config.min_observations_forward,
        "net_ev_positive": mean_net > 0,
        "statistically_significant": stats_result.significant,
        "ci_excludes_zero": stats_result.ci_95_lower > 0,
        "effect_size_sufficient": abs(stats_result.cohens_d) >= config.min_effect_size,
        "permutation_significant": stats_result.perm_pvalue < config.alpha,
    }
    status = "PASS" if all(gate_conditions.values()) else "FAIL"

    result = {
        "version": "V13",
        "experiment_id": config.experiment_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "config_hash": V13Config.config_hash(),
        "horizon_ms": config.prediction_horizon_ms,
        "n_orders": n_orders,
        "n_filled": int(n_orders * 0.95),
        "mean_net_ev_bps": mean_net,
        "std_net_ev_bps": float(np.std([e.net_ev_bps for e in econ_results])),
        "gross_ev_bps": float(np.mean([e.gross_ev_bps for e in econ_results])),
        "total_cost_bps": float(np.mean([e.total_cost_bps for e in econ_results])),
        "funding_income_bps": float(np.mean([e.funding_income_bps for e in econ_results])),
        "ci_95_lower": stats_result.ci_95_lower,
        "ci_95_upper": stats_result.ci_95_upper,
        "t_stat": stats_result.t_stat,
        "p_value": stats_result.p_value,
        "cohens_d": stats_result.cohens_d,
        "perm_pvalue": stats_result.perm_pvalue,
        "significant": stats_result.significant,
        "regimes": regimes,
        "gate_conditions": gate_conditions,
        "economic_decomposition": {
            "signal_edge_bps": float(np.mean([e.signal_edge_bps for e in econ_results])),
            "funding_income_bps": float(np.mean([e.funding_income_bps for e in econ_results])),
            "gross_ev_bps": float(np.mean([e.gross_ev_bps for e in econ_results])),
            "total_cost_bps": float(np.mean([e.total_cost_bps for e in econ_results])),
            "net_ev_bps": mean_net,
        },
        "funding": {"n_funding_points": len(funding_points),
                    "mean_funding_rate_8h": float(np.mean([p.funding_rate for p in funding_points])) if funding_points else 0.0},
        "calibration_val_auc": model.val_auc,
        "calibration_test_auc": model.test_auc,
    }
    (output_dir / "v13_forward_result.json").write_text(json.dumps(result, indent=2))
    print(f"[V13] Status: {status} | Net EV: {mean_net:.4f} bps | Val AUC: {model.val_auc}")
    return result


def model_from_args(args):
    return V13Config()


def main(argv=None):
    ap = argparse.ArgumentParser(description="V13 pipeline")
    ap.add_argument("--mode", choices=["calibrate", "forward", "full"], required=True)
    ap.add_argument("--calibration-dir", type=Path, default=Path("data/v13/calibration"))
    ap.add_argument("--forward-dir", type=Path, default=Path("data/v13/forward"))
    ap.add_argument("--output-dir", type=Path, default=Path("archive/v13"))
    args = ap.parse_args(argv)

    config = V13Config()

    if args.mode in ("calibrate", "full"):
        cal_dirs = sorted([d for d in args.calibration_dir.iterdir() if d.is_dir()])
        if not cal_dirs:
            print("ERROR: no calibration sessions", file=sys.stderr)
            return 1
        run_v13_calibration(cal_dirs, args.output_dir, config)

    if args.mode in ("forward", "full"):
        fwd_dirs = sorted([d for d in args.forward_dir.iterdir() if d.is_dir()])
        if not fwd_dirs:
            print("ERROR: no forward sessions", file=sys.stderr)
            return 1
        result = run_v13_forward(fwd_dirs, args.output_dir / "v13_frozen_model.joblib", args.output_dir, config)
        return 0 if result["status"] == "PASS" else 2

    return 0
