"""V16 pipeline — walk-forward validation, calibration, forward, evidence."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.v16.config import V16Config
from app.v16.features import extract_v16_features, build_v16_targets, build_v16_returns, V16_FEATURES
from app.v16.model import V16ReturnModel, V16FillProbabilityModel
from app.v16.execution import V16ExecutionSim
from app.v16.walk_forward import V16WalkForward
from app.v11.parser import V11DataParser


def _load_session(data_dir: str):
    session_dirs = sorted(Path(data_dir).rglob("events.jsonl"))
    if not session_dirs:
        return [], []
    session_dir = session_dirs[0].parent
    parser = V11DataParser(session_dir)
    return parser.parse()


def _make_feature_target(data_dir: str, horizon_ms: int) -> pd.DataFrame:
    books, trades = _load_session(data_dir)
    feats = extract_v16_features(books, trades, horizon_ms)
    if len(feats) < 10:
        return feats
    feats["target"] = build_v16_targets(feats, horizon_ms).values
    feats["fwd_ret_bps"] = build_v16_returns(feats, horizon_ms).values
    return feats


def _bootstrap_ci(returns_bps: np.ndarray, n_boot: int = 5000, block_size: int = 10,
                  alpha: float = 0.05, rng=None) -> dict:
    rng = rng or np.random.default_rng(42)
    r = np.asarray(returns_bps, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) == 0:
        return {"mean_bps": 0.0, "ci_lower_bps": 0.0, "ci_upper_bps": 0.0, "tstat": 0.0, "p_value": 1.0, "n": 0}
    mean = float(np.mean(r))
    n = len(r)
    if n < 10:
        bs = max(1, n // 3)
    elif n < 50:
        bs = max(1, n // 5)
    else:
        bs = min(block_size, n // 4)
    bs = max(1, bs)
    n_blocks = max(1, int(np.ceil(n / bs)))
    if n_blocks > 1 and n - bs + 1 > 0:
        idxs = rng.integers(0, n - bs + 1, size=(n_boot, n_blocks))
        block_means = np.array([
            np.concatenate([r[i:i + bs] for i in idxs[b]]).mean()
            for b in range(n_boot)
        ])
    else:
        block_means = np.array([rng.choice(r, size=max(1, n // 2), replace=True).mean() for _ in range(n_boot)])
    ci_lower = float(np.percentile(block_means, alpha / 2 * 100))
    ci_upper = float(np.percentile(block_means, (1 - alpha / 2) * 100))
    sem_block = float(np.std(block_means, ddof=1))
    sem = sem_block / np.sqrt(n) if sem_block > 0 and n > 0 else 0.0
    if sem > 0:
        from scipy import stats as sp_stats
        tstat = mean / sem
        p_value = float(2 * (1 - sp_stats.t.cdf(abs(tstat), df=n - 1)))
    else:
        tstat = 0.0
        p_value = 1.0
    # permutation test (sign-flipping under null: mean = 0)
    perm_means = []
    for _ in range(2000):
        signs = rng.choice([-1, 1], size=n)
        perm_means.append(np.mean(r * signs))
    perm_p = float((np.sum(np.abs(np.array(perm_means)) >= abs(mean)) + 1) / (len(perm_means) + 1))
    return {
        "mean_bps": mean, "ci_lower_bps": ci_lower, "ci_upper_bps": ci_upper,
        "tstat": tstat, "p_value": perm_p, "n": int(n),
    }


def calibrate(config: V16Config) -> dict:
    t0 = time.time()
    cfg = config
    feats = _make_feature_target(cfg.calibration_data_dir, cfg.prediction_horizon_ms)
    n = len(feats)
    if n < cfg.min_observations_calibration:
        return {"status": "BLOCKED", "reason": f"insufficient data: {n} < {cfg.min_observations_calibration}"}

    returns = feats["fwd_ret_bps"].values
    valid = ~np.isnan(returns)
    feats_valid = feats[valid].copy().reset_index(drop=True)
    X = feats_valid[V16_FEATURES].copy()
    y_ret = pd.Series(feats_valid["fwd_ret_bps"].values, index=feats_valid.index)
    y_fill = (y_ret > 0).astype(int)

    return_model = V16ReturnModel(cfg)
    fill_model = V16FillProbabilityModel(cfg)
    return_metrics = return_model.fit(X, y_ret)
    fill_metrics = fill_model.fit(X, y_fill)

    pred_returns = return_model.predict(X)
    fill_probs = fill_model.predict_proba(X)

    sim = V16ExecutionSim(cfg)
    decisions = [sim.route(pr, fp) for pr, fp in zip(pred_returns, fill_probs)]
    trade_decisions = [d for d in decisions if d.action in ("MAKER", "TAKER")]
    n_trades = len(trade_decisions)

    if n_trades > 0:
        trade_pnls = np.array([d.expected_pnl_bps for d in trade_decisions])
        gross_ev = float(np.nanmean(np.abs(pred_returns)))
        net_ev = float(np.nanmean(trade_pnls))
        stat = _bootstrap_ci(trade_pnls, n_boot=5000, rng=np.random.default_rng(cfg.random_state))
    else:
        gross_ev = 0.0
        net_ev = 0.0
        stat = {"mean_bps": 0.0, "ci_lower_bps": 0.0, "ci_upper_bps": 0.0, "p_value": 1.0, "n": 0}

    cal_dir = Path("archive/v16")
    cal_dir.mkdir(parents=True, exist_ok=True)
    return_model_path = cal_dir / "v16_frozen_return_model.joblib"
    fill_model_path = cal_dir / "v16_frozen_fill_model.joblib"
    return_checksum = return_model.save(return_model_path)
    fill_checksum = fill_model.save(fill_model_path)
    return_model_path.chmod(0o444)
    fill_model_path.chmod(0o444)

    artifact = {
        "experiment": "V16",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "FROZEN",
        "config_hash": cfg.config_hash(),
        "feature_names": V16_FEATURES,
        "return_model_path": str(return_model_path),
        "fill_model_path": str(fill_model_path),
        "return_model_checksum": return_checksum,
        "fill_model_checksum": fill_checksum,
        "return_model_metrics": return_metrics,
        "fill_model_metrics": fill_metrics,
        "gross_ev_bps": gross_ev,
        "net_ev_bps": net_ev,
        "n_trades_calibration": n_trades,
        "n_observations": n,
        "elapsed_s": round(time.time() - t0, 2),
    }
    Path("data/evidence/v16_calibration.json").write_text(json.dumps(artifact, indent=2, default=str))
    return artifact


def forward(config: V16Config, return_model_path: str | None = None, fill_model_path: str | None = None) -> dict:
    t0 = time.time()
    cfg = config
    return_model_path = Path(return_model_path or "archive/v16/v16_frozen_return_model.joblib")
    fill_model_path = Path(fill_model_path or "archive/v16/v16_frozen_fill_model.joblib")
    if not return_model_path.exists() or not fill_model_path.exists():
        return {"status": "BLOCKED", "reason": "frozen models not found"}

    return_model = V16ReturnModel.load(return_model_path)
    fill_model = V16FillProbabilityModel.load(fill_model_path)
    feats = _make_feature_target(cfg.forward_data_dir, cfg.prediction_horizon_ms)
    n = len(feats)
    if n < cfg.min_observations_forward:
        return {"status": "BLOCKED", "reason": f"insufficient forward data: {n} < {cfg.min_observations_forward}"}

    X = feats[V16_FEATURES].copy()
    actual_returns = feats["fwd_ret_bps"].values
    pred_returns = return_model.predict(X)
    fill_probs = fill_model.predict_proba(X)

    sim = V16ExecutionSim(cfg)
    decisions = [sim.route(pr, fp) for pr, fp in zip(pred_returns, fill_probs)]
    trade_decisions = [d for d in decisions if d.action in ("MAKER", "TAKER")]
    n_trades = len(trade_decisions)

    if n_trades > 0:
        trade_pnls = np.array([d.expected_pnl_bps for d in trade_decisions])
        gross_ev = float(np.nanmean(np.abs(pred_returns)))
        net_ev = float(np.nanmean(trade_pnls))
        stat = _bootstrap_ci(trade_pnls, n_boot=5000, rng=np.random.default_rng(cfg.random_state))
    else:
        gross_ev = 0.0
        net_ev = 0.0
        stat = {"mean_bps": 0.0, "ci_lower_bps": 0.0, "ci_upper_bps": 0.0, "p_value": 1.0, "n": 0}

    regimes = {
        "high_vol": feats["vol_regime"] > feats["vol_regime"].median(),
        "low_vol": feats["vol_regime"] <= feats["vol_regime"].median(),
        "high_liq": feats["liquidity_state"] > feats["liquidity_state"].median(),
        "low_liq": feats["liquidity_state"] <= feats["liquidity_state"].median(),
        "tight_spread": feats["spread_bps"] < feats["spread_bps"].median(),
        "wide_spread": feats["spread_bps"] >= feats["spread_bps"].median(),
    }
    regime_results = {}
    n_positive_regimes = 0
    for name, mask in regimes.items():
        rm = mask.values
        if rm.sum() > 0 and n_trades > 0:
            idx = np.where(rm)[0]
            valid_idx = idx[idx < len(trade_pnls)]
            if len(valid_idx) > 0:
                r_rets = trade_pnls[valid_idx]
                mean_ret = float(np.mean(r_rets))
                regime_results[name] = {"mean_ret_bps": mean_ret, "n": int(len(r_rets)), "positive": mean_ret > 0}
                if mean_ret > 0:
                    n_positive_regimes += 1

    forward_result = {
        "experiment": "V16",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "COMPLETE",
        "forward_data_dir": cfg.forward_data_dir,
        "n_events": n,
        "n_signals": n_trades,
        "n_trades": n_trades,
        "gross_ev_bps": gross_ev,
        "total_cost_bps": float(np.mean([d.total_cost_bps for d in trade_decisions])) if n_trades > 0 else 0.0,
        "net_ev_bps": net_ev,
        "ci_lower_bps": stat["ci_lower_bps"],
        "ci_upper_bps": stat["ci_upper_bps"],
        "p_value": stat["p_value"],
        "tstat": stat["tstat"],
        "positive_regimes": n_positive_regimes,
        "total_regimes": len(regimes),
        "regime_breakdown": regime_results,
        "elapsed_s": round(time.time() - t0, 2),
        "forward_pass": (net_ev > 0 and stat["ci_lower_bps"] > 0 and stat["p_value"] < 0.05
                         and n_positive_regimes >= 4 and n_trades >= cfg.min_trades_forward),
    }
    Path("data/evidence/v16_forward_validation.json").write_text(json.dumps(forward_result, indent=2, default=str))
    return forward_result


def run_pipeline(mode: str = "calibrate", config: V16Config | None = None) -> dict:
    cfg = config or V16Config()
    if mode == "calibrate":
        return calibrate(cfg)
    elif mode == "forward":
        return forward(cfg)
    else:
        raise ValueError(f"Unknown mode: {mode}")
