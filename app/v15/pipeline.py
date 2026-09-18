"""V15 pipeline — calibrate, freeze, forward, with evidence persistence."""
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

from app.v15.config import V15Config
from app.v15.features import extract_v15_features, build_v15_targets, build_v15_returns, V15_FEATURES
from app.v15.model import V15SignalModel
from app.v15.execution import V15ExecutionRouter, V15ExecutionDecision
from app.v15.regime import V15RegimeFilter
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
    feats = extract_v15_features(books, trades, horizon_ms)
    if len(feats) < 10:
        return feats
    feats["target"] = build_v15_targets(feats, horizon_ms).values
    feats["fwd_ret_bps"] = build_v15_returns(feats, horizon_ms).values
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
    perm_stats = []
    for _ in range(2000):
        perm = rng.permutation(r)
        perm_stats.append(perm.mean())
    perm_p = float((np.sum(np.array(perm_stats) >= mean) + 1) / (len(perm_stats) + 1))
    return {
        "mean_bps": mean, "ci_lower_bps": ci_lower, "ci_upper_bps": ci_upper,
        "tstat": tstat, "p_value": perm_p, "n": int(n),
    }


def calibrate(config: V15Config) -> dict:
    t0 = time.time()
    cfg = config
    feats = _make_feature_target(cfg.calibration_data_dir, cfg.prediction_horizon_ms)
    n = len(feats)
    if n < cfg.min_observations_calibration:
        return {"status": "BLOCKED", "reason": f"insufficient data: {n} < {cfg.min_observations_calibration}"}

    returns = feats["fwd_ret_bps"].values
    valid = ~np.isnan(returns)
    feats_valid = feats[valid].copy()
    X = feats_valid[V15_FEATURES].copy()
    y = pd.Series(feats_valid["fwd_ret_bps"].values, index=feats_valid.index)

    model = V15SignalModel(cfg)
    metrics = model.fit(X, y)

    # Execution router evaluation
    router = V15ExecutionRouter(cfg)
    regime = V15RegimeFilter()
    # Use same valid mask for regime filter
    regime_mask_full = regime.fit(feats).filter(feats)
    regime_mask_valid = regime_mask_full[valid].reset_index(drop=True)
    pred_returns = model.predict(X)
    decisions = [router.route(pr, bool(regime_mask_valid.iloc[i] if i < len(regime_mask_valid) else False))
                 for i, pr in enumerate(pred_returns)]
    trade_decisions = [d for d in decisions if d.action in ("MAKER", "TAKER")]
    n_trades = len(trade_decisions)

    if n_trades > 0:
        trade_returns = np.array([d.expected_net_edge_bps for d in trade_decisions])
        gross_ev = float(np.nanmean(np.abs(pred_returns[regime_mask_valid.values]))) if regime_mask_valid.sum() > 0 else 0.0
        net_ev = float(np.nanmean(trade_returns))
        stat = _bootstrap_ci(trade_returns, n_boot=5000, rng=np.random.default_rng(cfg.random_state))
    else:
        gross_ev = 0.0
        net_ev = 0.0
        stat = {"mean_bps": 0.0, "ci_lower_bps": 0.0, "ci_upper_bps": 0.0, "p_value": 1.0, "n": 0}

    cal_dir = Path("archive/v15")
    cal_dir.mkdir(parents=True, exist_ok=True)
    model_path = cal_dir / "v15_frozen_model.joblib"
    model_checksum = model.save(model_path)
    model_path.chmod(0o444)

    artifact = {
        "experiment": "V15",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "FROZEN",
        "config_hash": cfg.config_hash(),
        "feature_names": V15_FEATURES,
        "model_path": str(model_path),
        "model_checksum": model_checksum,
        "model_architecture": f"GradientBoostingRegressor(n={cfg.n_estimators}, depth={cfg.max_depth})",
        "calibration_metrics": metrics,
        "gross_ev_bps": gross_ev,
        "net_ev_bps": net_ev,
        "n_trades_calibration": n_trades,
        "n_observations": n,
        "regime_summary": regime.summary(),
        "elapsed_s": round(time.time() - t0, 2),
    }
    Path("data/evidence/v15_calibration.json").write_text(json.dumps(artifact, indent=2, default=str))
    return artifact


def forward(config: V15Config, frozen_model_path: str | None = None) -> dict:
    t0 = time.time()
    cfg = config
    model_path = Path(frozen_model_path or "archive/v15/v15_frozen_model.joblib")
    if not model_path.exists():
        return {"status": "BLOCKED", "reason": "frozen model not found"}

    model = V15SignalModel.load(model_path)
    feats = _make_feature_target(cfg.forward_data_dir, cfg.prediction_horizon_ms)
    n = len(feats)
    if n < cfg.min_observations_forward:
        return {"status": "BLOCKED", "reason": f"insufficient forward data: {n} < {cfg.min_observations_forward}"}

    X = feats[V15_FEATURES].copy()
    pred_returns = model.predict(X)
    actual_returns = feats["fwd_ret_bps"].values

    router = V15ExecutionRouter(cfg)
    regime = V15RegimeFilter()
    regime_mask = regime.fit(feats).filter(feats)

    n_total = len(feats)
    n_regime = int(regime_mask.sum())
    decisions = []
    trade_returns = []
    total_cost = 0.0

    for i in range(n_total):
        pr = float(pred_returns[i])
        reg = bool(regime_mask.iloc[i]) if i < len(regime_mask) else False
        decision = router.route(pr, reg)
        decisions.append(decision)
        if decision.action in ("MAKER", "TAKER"):
            cost = decision.total_cost_bps
            total_cost += cost
            trade_returns.append(actual_returns[i] - cost)

    n_trades = len(trade_returns)
    trade_arr = np.array(trade_returns, dtype=float)

    if n_trades > 0:
        gross_ev = float(np.nanmean(np.abs(actual_returns[regime_mask.values])))
        net_ev = float(np.nanmean(trade_arr))
        stat = _bootstrap_ci(trade_arr, n_boot=5000, rng=np.random.default_rng(cfg.random_state))
    else:
        gross_ev = 0.0
        net_ev = 0.0
        stat = {"mean_bps": 0.0, "ci_lower_bps": 0.0, "ci_upper_bps": 0.0, "p_value": 1.0, "n": 0}

    # Regime breakdown
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
        if rm.sum() > 0:
            r_rets = np.array([trade_returns[j] for j in range(n_trades) if rm[j % len(rm)] and j < len(trade_returns)])
            if len(r_rets) > 0:
                mean_ret = float(np.mean(r_rets))
                regime_results[name] = {"mean_ret_bps": mean_ret, "n": int(len(r_rets)), "positive": mean_ret > 0}
                if mean_ret > 0:
                    n_positive_regimes += 1

    forward_result = {
        "experiment": "V15",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "COMPLETE",
        "forward_data_dir": cfg.forward_data_dir,
        "n_events": n,
        "n_regime_filter_pass": n_regime,
        "n_signals": n_trades,
        "n_trades": n_trades,
        "gross_ev_bps": gross_ev,
        "total_cost_bps": float(np.mean([d.total_cost_bps for d in decisions if d.action != "NONE"])) if n_trades > 0 else 0.0,
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
                         and n_positive_regimes >= 4 and n_trades >= 50),
    }
    Path("data/evidence/v15_forward_validation.json").write_text(json.dumps(forward_result, indent=2, default=str))
    return forward_result


def run_pipeline(mode: str = "calibrate", config: V15Config | None = None) -> dict:
    cfg = config or V15Config()
    if mode == "calibrate":
        return calibrate(cfg)
    elif mode == "forward":
        return forward(cfg)
    else:
        raise ValueError(f"Unknown mode: {mode}")
