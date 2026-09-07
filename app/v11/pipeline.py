#!/usr/bin/env python3
"""V11 research experiment pipeline.

Pre-registered protocol: archive/v11/V11_PRE_REGISTERED_PROTOCOL.md

Usage:
    python -m app.v11.pipeline --calibration-dir data/v11_calibration --forward-dir data/v11_forward --output-dir archive/v11
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from .parser import V11DataParser
from .features import extract_v11_features, build_targets, build_regression_target, V11_FEATURES
from .model import V11SignalModel, V11SignalConfig
from .execution_model import V11ExecutionModel, V11ExecutionConfig, ExecutionResult
from .statistics import validate_statistics, analyze_regimes


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
    "min_observations_calibration": 100,
    "min_observations_forward": 100,
    "alpha": 0.05,
    "min_effect_size": 0.3,
    "model": "GradientBoostingClassifier",
    "features": V11_FEATURES,
}


def compute_net_ev_series(
    predicted_returns: pd.Series,
    fill_probabilities: pd.Series,
    execution_model: V11ExecutionModel,
    spread_bps: float = 0.013,
) -> pd.Series:
    """Compute per-order net EV series — matches execution_model.simulate_taker economics."""
    filled = (fill_probabilities > 0.5).astype(float)
    # Revenue = predicted return minus spread paid (taker crosses spread)
    gross = filled * (predicted_returns - spread_bps)
    # Cost = taker fee + slippage + adverse selection + latency (all on filled orders)
    cost = filled * execution_model.total_cost_bps
    return gross - cost


@dataclass
class V11CalibrationResult:
    n_sessions: int
    n_observations: int
    train_auc: float
    val_auc: float
    test_auc: float
    brier: float | None
    n_positive: int
    n_negative: int
    model_path: str
    model_checksum: str
    feature_names: list[str]
    protocol: dict[str, Any]


@dataclass
class V11ForwardResult:
    status: str
    n_orders: int
    n_filled: int
    mean_net_ev_bps: float
    std_net_ev_bps: float
    gross_ev_bps: float
    total_cost_bps: float
    ci_95_lower: float
    ci_95_upper: float
    t_stat: float
    p_value: float
    cohens_d: float
    perm_pvalue: float
    significant: bool
    regimes: dict[str, Any]
    gate_conditions: dict[str, bool]
    economic_decomposition: dict[str, float]


def _file_checksum(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()[:16]


def _session_checksums(session_dir: Path) -> str:
    """Compute aggregate checksum for a session."""
    h = hashlib.sha256()
    for fname in ["events.jsonl", "snapshot.json", "manifest.json"]:
        fpath = session_dir / fname
        if fpath.exists():
            with open(fpath, "rb") as f:
                while chunk := f.read(8192):
                    h.update(chunk)
    return h.hexdigest()[:16]


def parse_session(session_dir: Path) -> tuple[list[Any], list[Any]]:
    """Parse a single session directory."""
    parser = V11DataParser(session_dir)
    return parser.parse()


def run_v11_calibration(calibration_dirs: list[Path], output_dir: Path) -> V11CalibrationResult:
    """Run V11 calibration pipeline."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_books: list[Any] = []
    all_trades: list[Any] = []
    session_checksums = {}

    print(f"[V11] Parsing {len(calibration_dirs)} calibration sessions...")
    for d in calibration_dirs:
        books, trades = parse_session(d)
        session_checksums[d.name] = _session_checksums(d)
        all_books.extend(books)
        all_trades.extend(trades)
        print(f"  {d.name}: {len(books)} book snapshots, {len(trades)} trades")

    all_books.sort(key=lambda b: b.ts_ms)
    all_trades.sort(key=lambda t: t.ts_ms)

    print(f"[V11] Extracting features from {len(all_books)} book snapshots...")
    df = extract_v11_features(all_books, all_trades, window_ms=PROTOCOL["horizon_ms"])
    df["target"] = build_targets(df, horizon_ms=PROTOCOL["horizon_ms"]).values

    df = df.dropna(subset=["target"])
    df = df[df["target"].isin([0, 1])]

    n_obs = len(df)
    print(f"[V11] Calibration observations: {n_obs}")
    if n_obs < PROTOCOL["min_observations_calibration"]:
        print(f"[V11] WARNING: insufficient calibration observations ({n_obs} < {PROTOCOL['min_observations_calibration']})")

    config = V11SignalConfig(prediction_horizon_ms=PROTOCOL["horizon_ms"])
    model = V11SignalModel(config)
    feature_cols = [c for c in V11_FEATURES if c in df.columns]
    X = df[feature_cols].copy()
    y = df["target"].copy()

    print("[V11] Training gradient-boosted model...")
    # Compute actual returns for calibration
    actual_returns = build_regression_target(df, horizon_ms=PROTOCOL["horizon_ms"])
    metrics = model.fit(X, y, returns=actual_returns)
    print(f"  Train AUC: {metrics['train_auc']:.4f}")
    print(f"  Val AUC:   {metrics['val_auc']:.4f}")
    print(f"  Test AUC:  {metrics['test_auc']:.4f}")
    if metrics.get("return_calibration_bins"):
        print(f"  Return calibration bins: {metrics['return_calibration_bins']}")

    model_path = output_dir / "v11_frozen_model.joblib"
    model.save(model_path)
    model_checksum = _file_checksum(model_path)
    print(f"[V11] Frozen model saved: {model_path} (checksum: {model_checksum})")

    cal_artifact = {
        "version": "V11",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "CALIBRATED",
        "protocol": PROTOCOL,
        "sessions": {k: {"checksum": v} for k, v in session_checksums.items()},
        "n_sessions": len(calibration_dirs),
        "n_observations": n_obs,
        "metrics": metrics,
        "model_path": str(model_path),
        "model_checksum": model_checksum,
        "feature_names": feature_cols,
    }
    cal_path = output_dir / "v11_calibration_artifact.json"
    with open(cal_path, "w") as f:
        json.dump(cal_artifact, f, indent=2)
    print(f"[V11] Calibration artifact saved: {cal_path}")

    return V11CalibrationResult(
        n_sessions=len(calibration_dirs),
        n_observations=n_obs,
        train_auc=metrics["train_auc"],
        val_auc=metrics["val_auc"],
        test_auc=metrics["test_auc"],
        brier=metrics.get("brier"),
        n_positive=metrics["n_positive"],
        n_negative=metrics["n_negative"],
        model_path=str(model_path),
        model_checksum=model_checksum,
        feature_names=feature_cols,
        protocol=PROTOCOL,
    )


def run_v11_forward(
    forward_dirs: list[Path],
    model_path: Path,
    output_dir: Path,
    execution_model: V11ExecutionModel,
) -> V11ForwardResult:
    """Run V11 independent forward validation."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    model = V11SignalModel.load(model_path)
    print(f"[V11] Loaded frozen model (val_auc={model._val_auc})")

    all_books: list[Any] = []
    all_trades: list[Any] = []

    print(f"[V11] Parsing {len(forward_dirs)} forward sessions...")
    for d in forward_dirs:
        books, trades = parse_session(d)
        all_books.extend(books)
        all_trades.extend(trades)
        print(f"  {d.name}: {len(books)} book snapshots, {len(trades)} trades")

    all_books.sort(key=lambda b: b.ts_ms)
    all_trades.sort(key=lambda t: t.ts_ms)

    print(f"[V11] Extracting features from {len(all_books)} forward book snapshots...")
    df = extract_v11_features(all_books, all_trades, window_ms=PROTOCOL["horizon_ms"])
    df["target"] = build_targets(df, horizon_ms=PROTOCOL["horizon_ms"]).values
    df = df.dropna(subset=["target"])
    df = df[df["target"].isin([0, 1])]

    n_orders = len(df)
    print(f"[V11] Forward observations: {n_orders}")
    if n_orders < PROTOCOL["min_observations_forward"]:
        print(f"[V11] WARNING: insufficient forward observations ({n_orders} < {PROTOCOL['min_observations_forward']})")

    feature_cols = model._feature_names
    X = df[feature_cols].copy()
    X = X.replace([np.inf, -np.inf], 0.0).fillna(0.0)
    predicted_probs = model.predict_proba(X)
    predicted_returns = pd.Series(model.predict_returns(X), index=df.index)

    actual_spread = df["spread_bps"].mean() if "spread_bps" in df.columns else 0.013

    # Execution simulation
    exec_result = execution_model.simulate_taker(
        predicted_returns=predicted_returns,
        fill_probabilities=predicted_probs,
        spread_bps=actual_spread,
    )

    net_ev = compute_net_ev_series(
        predicted_returns,
        predicted_probs,
        execution_model,
        spread_bps=actual_spread,
    )

    stats_result = validate_statistics(net_ev, alpha=PROTOCOL["alpha"])
    regimes = analyze_regimes(net_ev, df)

    gate_conditions = {
        "sufficient_observations": n_orders >= PROTOCOL["min_observations_forward"],
        "net_ev_positive": stats_result.mean_net_ev_bps > 0,
        "statistically_significant": stats_result.significant,
        "ci_excludes_zero": stats_result.ci_95_lower > 0,
        "effect_size_sufficient": abs(stats_result.cohens_d) >= PROTOCOL["min_effect_size"],
        "permutation_significant": stats_result.perm_pvalue < PROTOCOL["alpha"],
    }
    all_pass = all(gate_conditions.values())
    status = "PASS" if all_pass else "FAIL"

    econ = {
        "signal_edge_bps": float((predicted_probs * 10.0).mean()),
        "gross_ev_bps": float(exec_result.gross_ev_bps),
        "fees_bps": float(exec_result.fees_bps),
        "slippage_bps": float(exec_result.slippage_bps),
        "adverse_selection_bps": float(exec_result.adverse_selection_bps),
        "total_cost_bps": float(exec_result.total_cost_bps),
        "net_ev_bps": float(exec_result.net_ev_bps),
        "fill_probability": float(exec_result.fill_probability),
        "breakeven_return_bps": float(execution_model.breakeven_return_bps(exec_result.fill_probability)),
    }

    result = V11ForwardResult(
        status=status,
        n_orders=n_orders,
        n_filled=exec_result.n_filled,
        mean_net_ev_bps=stats_result.mean_net_ev_bps,
        std_net_ev_bps=stats_result.std_net_ev_bps,
        gross_ev_bps=exec_result.gross_ev_bps,
        total_cost_bps=exec_result.total_cost_bps,
        ci_95_lower=stats_result.ci_95_lower,
        ci_95_upper=stats_result.ci_95_upper,
        t_stat=stats_result.t_stat,
        p_value=stats_result.p_value,
        cohens_d=stats_result.cohens_d,
        perm_pvalue=stats_result.perm_pvalue,
        significant=stats_result.significant,
        regimes=regimes,
        gate_conditions=gate_conditions,
        economic_decomposition=econ,
    )

    result_path = output_dir / "v11_forward_result.json"
    result_dict = {
        "version": "V11",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "n_orders": n_orders,
        "n_filled": exec_result.n_filled,
        "mean_net_ev_bps": stats_result.mean_net_ev_bps,
        "std_net_ev_bps": stats_result.std_net_ev_bps,
        "gross_ev_bps": exec_result.gross_ev_bps,
        "total_cost_bps": exec_result.total_cost_bps,
        "ci_95_lower": stats_result.ci_95_lower,
        "ci_95_upper": stats_result.ci_95_upper,
        "t_stat": stats_result.t_stat,
        "p_value": stats_result.p_value,
        "cohens_d": stats_result.cohens_d,
        "perm_pvalue": stats_result.perm_pvalue,
        "significant": stats_result.significant,
        "regimes": regimes,
        "gate_conditions": gate_conditions,
        "economic_decomposition": econ,
    }
    with open(result_path, "w") as f:
        json.dump(result_dict, f, indent=2)
    print(f"[V11] Forward result saved: {result_path}")

    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description="V11 research experiment pipeline")
    ap.add_argument("--calibration-dir", type=Path, required=True, help="Directory with calibration sessions")
    ap.add_argument("--forward-dir", type=Path, required=True, help="Directory with forward sessions")
    ap.add_argument("--output-dir", type=Path, default=Path("archive/v11"), help="Output directory")
    args = ap.parse_args(argv)

    cal_dirs = sorted([d for d in args.calibration_dir.iterdir() if d.is_dir()])
    fwd_dirs = sorted([d for d in args.forward_dir.iterdir() if d.is_dir()])

    if not cal_dirs:
        print("ERROR: no calibration sessions found", file=sys.stderr)
        return 1
    if not fwd_dirs:
        print("ERROR: no forward sessions found", file=sys.stderr)
        return 1

    cal_result = run_v11_calibration(cal_dirs, args.output_dir)
    model_path = Path(cal_result.model_path)
    execution_model = V11ExecutionModel(config=V11ExecutionConfig())
    fwd_result = run_v11_forward(fwd_dirs, model_path, args.output_dir, execution_model)

    print("\n" + "=" * 70)
    print("V11 FINAL RESULT")
    print("=" * 70)
    print(f"Status:               {fwd_result.status}")
    print(f"Forward observations: {fwd_result.n_orders}")
    print(f"Mean net EV (bps):    {fwd_result.mean_net_ev_bps:.4f}")
    print(f"95% CI:               [{fwd_result.ci_95_lower:.4f}, {fwd_result.ci_95_upper:.4f}]")
    print(f"p-value:              {fwd_result.p_value:.4f}")
    print(f"Permutation p-value:  {fwd_result.perm_pvalue:.4f}")
    print(f"Cohen's d:            {fwd_result.cohens_d:.4f}")
    print(f"Statistical sig:      {fwd_result.significant}")
    print(f"Gross EV (bps):       {fwd_result.gross_ev_bps:.4f}")
    print(f"Total cost (bps):     {fwd_result.total_cost_bps:.4f}")
    print(f"Gate conditions:")
    for k, v in fwd_result.gate_conditions.items():
        print(f"  {k}: {v}")
    print("=" * 70)

    return 0 if fwd_result.status == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
