#!/usr/bin/env python3
"""V12 research experiment pipeline.

Pre-registered protocol: data/research/V12_RESEARCH_BASIS.md

Usage:
    python -m app.v12.pipeline --mode calibrate
    python -m app.v12.pipeline --mode forward
    python -m app.v12.pipeline --mode full
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from .parser import V11DataParser
from .features import extract_v12_features, build_v12_targets, build_v12_returns
from .model import V12SignalModel, V12ModelConfig
from .execution_model import V12ExecutionModel
from .statistics import validate_statistics, analyze_regimes
from .config import V12Config
from .funding import fetch_and_cache, average_funding_rate_during


# ---------------------------------------------------------------------------
# Frozen protocol constants (pre-registered, immutable)
# ---------------------------------------------------------------------------
PROTOCOL = {
    "horizon_ms": 500,
    "taker_fee_bps": 5.0,
    "maker_fee_bps": 2.0,
    "slippage_bps": 0.5,
    "adverse_selection_bps": 0.5,
    "latency_bps": 0.1,
    "exit_cost_bps": 5.0,
    "funding_threshold_bps": 5.0,
    "min_observations_calibration": 100,
    "min_observations_forward": 100,
    "alpha": 0.05,
    "min_effect_size": 0.2,
    "model": "LogisticRegression",
    "features": [
        "ofi_l1", "ofi_norm_l1", "qi_l1", "di_l5", "di_l10",
        "mpd_bps", "spread_bps", "bid_cancel_bps", "ask_add_bps",
        "cancel_pressure", "tfi_500", "liq_depletion",
        "log_depth1", "log_depth5", "log_event_rate",
        "depth_slope_bps", "vol_500",
    ],
}


def _file_checksum(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()[:16]


def _session_checksums(session_dir: Path) -> str:
    h = hashlib.sha256()
    for fname in ["events.jsonl", "snapshot.json", "manifest.json"]:
        fpath = session_dir / fname
        if fpath.exists():
            with open(fpath, "rb") as f:
                while chunk := f.read(8192):
                    h.update(chunk)
    return h.hexdigest()[:16]


def parse_session(session_dir: Path) -> tuple[list, list]:
    parser = V11DataParser(session_dir)
    return parser.parse()


def run_v12_calibration(calibration_dirs: list[Path], output_dir: Path, config: V12Config) -> dict:
    """Run V12 calibration pipeline."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_books: list = []
    all_trades: list = []
    session_checksums = {}

    print(f"[V12] Parsing {len(calibration_dirs)} calibration sessions...")
    for d in calibration_dirs:
        books, trades = parse_session(d)
        session_checksums[d.name] = _session_checksums(d)
        all_books.extend(books)
        all_trades.extend(trades)
        print(f"  {d.name}: {len(books)} book snapshots, {len(trades)} trades")

    all_books.sort(key=lambda b: b.ts_ms)
    all_trades.sort(key=lambda t: t.ts_ms)

    print(f"[V12] Extracting features from {len(all_books)} book snapshots...")
    df = extract_v12_features(all_books, all_trades, window_ms=PROTOCOL["horizon_ms"])
    df["target"] = build_v12_targets(df, horizon_ms=PROTOCOL["horizon_ms"]).values
    df["actual_return"] = build_v12_returns(df, horizon_ms=PROTOCOL["horizon_ms"]).values

    df = df.dropna(subset=["target", "actual_return"])
    df = df[df["target"].isin([0, 1])]

    n_obs = len(df)
    print(f"[V12] Calibration observations: {n_obs}")

    model_config = V12ModelConfig()
    model = V12SignalModel(model_config)
    feature_cols = [c for c in PROTOCOL["features"] if c in df.columns]
    X = df[feature_cols].copy()
    y = df["target"].copy()
    returns = df["actual_return"].copy()

    print("[V12] Training logistic regression model...")
    metrics = model.fit(X, y, returns=returns)
    print(f"  Train AUC: {metrics['train_auc']:.4f}")
    print(f"  Val AUC:   {metrics['val_auc']:.4f}")
    print(f"  Test AUC:  {metrics['test_auc']:.4f}")

    model_path = output_dir / "v12_frozen_model.joblib"
    model_checksum = model.save(model_path)
    print(f"[V12] Frozen model saved: {model_path} (checksum: {model_checksum})")

    cal_artifact = {
        "version": "V12",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "CALIBRATED",
        "protocol": PROTOCOL,
        "config_hash": V12Config.config_hash(),
        "sessions": {k: {"checksum": v} for k, v in session_checksums.items()},
        "n_sessions": len(calibration_dirs),
        "n_observations": n_obs,
        "metrics": metrics,
        "model_path": str(model_path),
        "model_checksum": model_checksum,
        "feature_names": feature_cols,
    }
    cal_path = output_dir / "v12_calibration_artifact.json"
    with open(cal_path, "w") as f:
        json.dump(cal_artifact, f, indent=2)
    print(f"[V12] Calibration artifact saved: {cal_path}")

    return {
        "model_path": str(model_path),
        "model_checksum": model_checksum,
        "calibration_artifact": cal_artifact,
        "metrics": metrics,
    }


def run_v12_forward(
    forward_dirs: list[Path],
    model_path: Path,
    output_dir: Path,
    config: V12Config,
) -> dict:
    """Run V12 independent forward validation."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    model = V12SignalModel.load(model_path)
    print(f"[V12] Loaded frozen model (val_auc={model._val_auc})")

    execution_model = V12ExecutionModel(config=config)

    all_books: list = []
    all_trades: list = []

    print(f"[V12] Parsing {len(forward_dirs)} forward sessions...")
    for d in forward_dirs:
        books, trades = parse_session(d)
        all_books.extend(books)
        all_trades.extend(trades)
        print(f"  {d.name}: {len(books)} book snapshots, {len(trades)} trades")

    all_books.sort(key=lambda b: b.ts_ms)
    all_trades.sort(key=lambda t: t.ts_ms)

    print(f"[V12] Extracting features from {len(all_books)} forward book snapshots...")
    df = extract_v12_features(all_books, all_trades, window_ms=PROTOCOL["horizon_ms"])
    df["target"] = build_v12_targets(df, horizon_ms=PROTOCOL["horizon_ms"]).values
    df["actual_return"] = build_v12_returns(df, horizon_ms=PROTOCOL["horizon_ms"]).values
    df = df.dropna(subset=["target", "actual_return"])
    df = df[df["target"].isin([0, 1])]

    n_orders = len(df)
    print(f"[V12] Forward observations: {n_orders}")

    # Fetch real 8-hour funding rates covering the forward window (Rule 13).
    ts_series = df["ts_ms"].values
    fwd_start_ms = int(ts_series.min()) if n_orders > 0 else int(time.time() * 1000)
    fwd_end_ms = int(ts_series.max()) if n_orders > 0 else fwd_start_ms + 1
    # Widen the funding window to guarantee at least one 8h funding point
    # (funding updates every 8h; a short capture may contain none).
    fwd_start_ms = fwd_start_ms - 8 * 3600_000
    print(f"[V12] Fetching real funding rates for forward window [{fwd_start_ms}, {fwd_end_ms}]...")
    try:
        funding_points = fetch_and_cache(
            symbol=config.symbol,
            start_ms=fwd_start_ms,
            end_ms=fwd_end_ms,
            cache_path=output_dir / "v12_forward_funding_cache.json",
        )
    except Exception as exc:
        print(f"[V12] WARNING: funding fetch failed ({exc}); forward funding rate unavailable -> funding_income=0 documented")
        funding_points = []

    feature_cols = [c for c in model._feature_names if c in df.columns]
    X = df[feature_cols].copy()
    X = X.replace([np.inf, -np.inf], 0.0).fillna(0.0)
    predicted_probs = model.predict_proba(X)
    predicted_returns = model.predict_returns(X)

    # Economic decomposition with REAL funding rates
    actual_spread = df["spread_bps"].mean() if "spread_bps" in df.columns else 0.013
    hold_hours = config.max_holding_hours
    econ_results = []
    for i in range(len(df)):
        prob = predicted_probs[i]
        pred_ret = predicted_returns[i]
        ts = int(ts_series[i])
        # Average 8h funding rate over the expected holding window
        funding_rate = average_funding_rate_during(
            funding_points, ts, ts + int(hold_hours * 3600_000)
        )
        econ = execution_model.decompose_trade(
            signal_edge_bps=pred_ret,
            funding_rate_8h=funding_rate,
            hold_duration_hours=hold_hours,
            signal_confidence=prob,
            spread_bps=actual_spread,
        )
        econ_results.append(econ)

    mean_net_ev = float(np.mean([e.net_ev_bps for e in econ_results]))
    std_net_ev = float(np.std([e.net_ev_bps for e in econ_results]))
    gross_ev = float(np.mean([e.gross_ev_bps for e in econ_results]))
    total_cost = float(np.mean([e.total_cost_bps for e in econ_results]))
    funding_income = float(np.mean([e.funding_income_bps for e in econ_results]))

    net_ev_series = pd.Series([e.net_ev_bps for e in econ_results])
    from .statistics import validate_statistics, analyze_regimes
    stats_result = validate_statistics(net_ev_series, alpha=PROTOCOL["alpha"])
    regimes = analyze_regimes(net_ev_series, df)

    gate_conditions = {
        "sufficient_observations": n_orders >= PROTOCOL["min_observations_forward"],
        "net_ev_positive": mean_net_ev > 0,
        "statistically_significant": stats_result.significant,
        "ci_excludes_zero": stats_result.ci_95_lower > 0,
        "effect_size_sufficient": abs(stats_result.cohens_d) >= PROTOCOL["min_effect_size"],
        "permutation_significant": stats_result.perm_pvalue < PROTOCOL["alpha"],
    }
    all_pass = all(gate_conditions.values())
    status = "PASS" if all_pass else "FAIL"

    econ_agg = {
        "signal_edge_bps": float(np.mean([e.signal_edge_bps for e in econ_results])),
        "funding_income_bps": funding_income,
        "gross_ev_bps": gross_ev,
        "spread_paid_bps": float(np.mean([e.spread_paid_bps for e in econ_results])),
        "fees_bps": config.taker_fee_bps,
        "slippage_bps": config.slippage_bps,
        "adverse_selection_bps": config.adverse_selection_bps,
        "exit_cost_bps": 5.0,
        "total_cost_bps": total_cost,
        "net_ev_bps": mean_net_ev,
        "fill_probability": 0.95,
        "mean_funding_rate_8h": float(np.mean([
            average_funding_rate_during(funding_points, int(ts_series[i]), int(ts_series[i]) + int(hold_hours * 3600_000))
            for i in range(len(df))
        ])) if funding_points else 0.0,
        "n_funding_points": len(funding_points),
    }

    result = {
        "version": "V12",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "n_orders": n_orders,
        "n_filled": int(n_orders * 0.95),
        "mean_net_ev_bps": mean_net_ev,
        "std_net_ev_bps": std_net_ev,
        "gross_ev_bps": gross_ev,
        "total_cost_bps": total_cost,
        "funding_income_bps": funding_income,
        "ci_95_lower": stats_result.ci_95_lower,
        "ci_95_upper": stats_result.ci_95_upper,
        "t_stat": stats_result.t_stat,
        "p_value": stats_result.p_value,
        "cohens_d": stats_result.cohens_d,
        "perm_pvalue": stats_result.perm_pvalue,
        "significant": stats_result.significant,
        "regimes": regimes,
         "gate_conditions": gate_conditions,
         "economic_decomposition": econ_agg,
         "funding": {
             "n_funding_points": len(funding_points),
             "mean_funding_rate_8h": econ_agg["mean_funding_rate_8h"],
         },
     }

    result_path = output_dir / "v12_forward_result.json"
    with open(result_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"[V12] Forward result saved: {result_path}")

    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description="V12 research experiment pipeline")
    ap.add_argument("--mode", choices=["calibrate", "forward", "full"], required=True)
    ap.add_argument("--calibration-dir", type=Path, default=Path("data/v12/calibration"))
    ap.add_argument("--forward-dir", type=Path, default=Path("data/v12/forward"))
    ap.add_argument("--output-dir", type=Path, default=Path("archive/v12"))
    args = ap.parse_args(argv)

    config = V12Config()

    if args.mode in ("calibrate", "full"):
        cal_dirs = sorted([d for d in args.calibration_dir.iterdir() if d.is_dir()])
        if not cal_dirs:
            print("ERROR: no calibration sessions found", file=sys.stderr)
            return 1
        cal_result = run_v12_calibration(cal_dirs, args.output_dir, config)

    if args.mode in ("forward", "full"):
        fwd_dirs = sorted([d for d in args.forward_dir.iterdir() if d.is_dir()])
        if not fwd_dirs:
            print("ERROR: no forward sessions found", file=sys.stderr)
            return 1
        model_path = args.output_dir / "v12_frozen_model.joblib"
        if not model_path.exists():
            print("ERROR: frozen model not found, run calibration first", file=sys.stderr)
            return 1
        fwd_result = run_v12_forward(fwd_dirs, model_path, args.output_dir, config)

        print("\n" + "=" * 70)
        print("V12 FINAL RESULT")
        print("=" * 70)
        print(f"Status:               {fwd_result['status']}")
        print(f"Forward observations: {fwd_result['n_orders']}")
        print(f"Mean net EV (bps):    {fwd_result['mean_net_ev_bps']:.4f}")
        print(f"Funding income (bps): {fwd_result['funding_income_bps']:.4f}")
        print(f"95% CI:               [{fwd_result['ci_95_lower']:.4f}, {fwd_result['ci_95_upper']:.4f}]")
        print(f"p-value:              {fwd_result['p_value']:.4f}")
        print(f"Permutation p-value:  {fwd_result['perm_pvalue']:.4f}")
        print(f"Cohen's d:            {fwd_result['cohens_d']:.4f}")
        print(f"Statistical sig:      {fwd_result['significant']}")
        print(f"Gross EV (bps):       {fwd_result['gross_ev_bps']:.4f}")
        print(f"Funding income:       {fwd_result['funding_income_bps']:.4f}")
        print(f"Total cost (bps):     {fwd_result['total_cost_bps']:.4f}")
        print(f"Gate conditions:")
        for k, v in fwd_result['gate_conditions'].items():
            print(f"  {k}: {v}")
        print("=" * 70)

        return 0 if fwd_result['status'] == "PASS" else 2

    return 0


if __name__ == "__main__":
    sys.exit(main())