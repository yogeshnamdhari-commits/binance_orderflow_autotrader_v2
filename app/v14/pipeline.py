"""V14 pipeline — calibrate, freeze, forward, with evidence persistence."""
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

from app.v14.config import V14Config
from app.v14.features import extract_v14_features, build_v14_targets, build_v14_returns, V14_FEATURES
from app.v14.model import V14SignalModel
from app.v14.execution import V14ExecutionSim, V14EconomicDecomposition
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
    feats = extract_v14_features(books, trades, horizon_ms)
    if len(feats) < 10:
        return feats
    feats["target"] = build_v14_targets(feats, horizon_ms).values
    feats["fwd_ret_bps"] = build_v14_returns(feats, horizon_ms).values
    return feats


def _bootstrap_ci(returns_bps: np.ndarray, n_boot: int = 10000, block_size: int = 19,
                  alpha: float = 0.05, rng: np.random.Generator | None = None) -> dict:
    rng = rng or np.random.default_rng(42)
    r = np.asarray(returns_bps)
    r = r[~np.isnan(r)]
    if len(r) == 0:
        return {"mean_bps": 0.0, "ci_lower_bps": 0.0, "ci_upper_bps": 0.0, "tstat": 0.0, "p_value": 1.0, "n": 0}
    mean = float(np.mean(r))
    if len(r) < block_size:
        block_size = max(1, len(r) // 2)
    # block bootstrap (time dependence)
    n_blocks = int(np.ceil(len(r) / block_size))
    idxs = rng.integers(0, len(r) - block_size + 1, size=(n_boot, n_blocks))
    block_means = np.array([
        np.concatenate([r[i:i + block_size] for i in idxs[b]]).mean()
        for b in range(n_boot)
    ])
    ci_lower = float(np.percentile(block_means, alpha / 2 * 100))
    ci_upper = float(np.percentile(block_means, (1 - alpha / 2) * 100))
    sem = float(np.std(block_means, ddof=1) / np.sqrt(n_boot)) if n_boot > 1 else 0.0
    tstat = mean / sem if sem > 0 else 0.0
    p_value = float(2 * (1 - 0.5 * (1 + np.sign(abs(tstat)) * 0)))  # placeholder; use scipy below
    # permutation test
    perm_stats = []
    for _ in range(2000):
        perm = rng.permutation(r)
        perm_stats.append(perm.mean())
    perm_p = float((np.sum(np.array(perm_stats) >= mean) + 1) / (len(perm_stats) + 1))
    return {
        "mean_bps": mean,
        "ci_lower_bps": ci_lower,
        "ci_upper_bps": ci_upper,
        "tstat": tstat,
        "p_value": perm_p,
        "n": int(len(r)),
    }


def calibrate(config: V14Config) -> dict:
    ts = time.time
    t0 = ts()
    cfg = config
    feats = _make_feature_target(cfg.calibration_data_dir, cfg.prediction_horizon_ms)
    n = len(feats)
    if n < cfg.min_observations_calibration:
        return {"status": "BLOCKED", "reason": f"insufficient data: {n} < {cfg.min_observations_calibration}"}

    target = feats["target"].values
    returns = feats["fwd_ret_bps"].values
    X = feats[V14_FEATURES].copy()

    # Baseline 1: naive (no signal)
    baseline_naive_ev = float(np.nanmean(returns)) if len(returns) else 0.0

    # Baseline 2: simple order-flow (book imbalance L1 sign)
    simple_signals = (feats["book_imbalance_l1"].values > feats["book_imbalance_l1"].median()).astype(int)
    sim = V14ExecutionSim(cfg)
    simple_costs = np.where(simple_signals == 1, sim.entry_cost_bps + sim._cfg.exit_cost_bps, 0.0)
    baseline_simple_ev = float(np.nanmean(returns - simple_costs))

    # V14 candidate model
    model = V14SignalModel(cfg)
    calibrate_metrics = model.fit(X, pd.Series(target), pd.Series(returns))

    probs = model.predict_proba(X)
    pred_returns = model.predict_returns(X)

    # Economic simulation: only trade when confidence > breakeven threshold
    breakeven_cost = sim.total_roundtrip_cost_bps
    signal_edge = np.where(probs > 0.5, pred_returns, pred_returns)
    trade_mask = np.abs(pred_returns) > breakeven_cost  # confidence gate
    gross_ev = float(np.nanmean(np.where(trade_mask, returns, 0.0)))
    entry_costs = np.where(trade_mask, sim.entry_cost_bps, 0.0)
    exit_costs = np.where(trade_mask, sim._cfg.exit_cost_bps, 0.0)
    net_ev = float(np.nanmean(np.where(trade_mask, returns - entry_costs - exit_costs, 0.0)))

    # Statistical test on per-trade net returns
    trade_returns = np.where(trade_mask, returns - entry_costs - exit_costs, np.nan)
    trade_returns = trade_returns[~np.isnan(trade_returns)]
    stat = _bootstrap_ci(trade_returns, n_boot=5000, rng=np.random.default_rng(cfg.random_state))

    cal_dir = Path("archive/v14")
    cal_dir.mkdir(parents=True, exist_ok=True)

    train_data_hash = hashlib.sha256(feats.to_csv(index=False).encode()).hexdigest()[:16]
    feature_names_hash = hashlib.sha256(json.dumps(V14_FEATURES).encode()).hexdigest()[:16]
    model_path = cal_dir / "v14_frozen_model.joblib"
    model_checksum = model.save(model_path)
    model_path.chmod(0o444)

    artifact = {
        "experiment": "V14",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "FROZEN",
        "config_hash": cfg.config_hash(),
        "feature_names": V14_FEATURES,
        "feature_names_hash": feature_names_hash,
        "train_data_hash": train_data_hash,
        "train_data_session": cfg.calibration_data_dir,
        "model_path": str(model_path),
        "model_checksum": model_checksum,
        "model_architecture": "LogisticRegression(C={})".format(cfg.regularization_c),
        "calibration_metrics": calibrate_metrics,
        "baseline_naive_ev_bps": baseline_naive_ev,
        "baseline_simple_ev_bps": baseline_simple_ev,
        "breakeven_cost_bps": breakeven_cost,
        "calibration_gross_ev_bps": gross_ev,
        "calibration_net_ev_bps": net_ev,
        "calibration_total_cost_bps": float(sim.total_roundtrip_cost_bps),
        "calibration_total_cost_bps_actual": float(np.nanmean(entry_costs + exit_costs) * 2),
        "n_trades_calibration": int(trade_mask.sum()),
        "n_observations": n,
        "elapsed_s": round(ts() - t0, 2),
        "return_calibration": model._return_calibration,
    }
    Path("data/evidence/v14_calibration.json").write_text(json.dumps(artifact, indent=2, default=str))
    return artifact


def forward(config: V14Config, frozen_model_path: str | None = None) -> dict:
    t0 = time.time()
    cfg = config
    model_path = Path(frozen_model_path or "archive/v14/v14_frozen_model.joblib")
    if not model_path.exists():
        return {"status": "BLOCKED", "reason": "frozen model not found"}

    model = V14SignalModel.load(model_path)
    feats = _make_feature_target(cfg.forward_data_dir, cfg.prediction_horizon_ms)
    n = len(feats)
    if n < cfg.min_observations_forward:
        return {"status": "BLOCKED", "reason": f"insufficient forward data: {n} < {cfg.min_observations_forward}"}

    X = feats[V14_FEATURES].copy()
    probs = model.predict_proba(X)
    returns = feats["fwd_ret_bps"].values
    target = feats["target"].values

    sim = V14ExecutionSim(cfg)
    breakeven_cost = sim.total_roundtrip_cost_bps
    pred_returns = model.predict_returns(X)
    trade_mask = np.abs(pred_returns) > breakeven_cost

    entry_costs = np.where(trade_mask, sim.entry_cost_bps, 0.0)
    exit_costs = np.where(trade_mask, sim._cfg.exit_cost_bps, 0.0)
    costs = entry_costs + exit_costs
    gross_ev = float(np.nanmean(np.where(trade_mask, returns, 0.0)))
    net_ev = float(np.nanmean(np.where(trade_mask, returns - costs, 0.0)))

    trade_returns = np.where(trade_mask, returns - costs, np.nan)
    trade_returns_clean = trade_returns[~np.isnan(trade_returns)]
    stat = _bootstrap_ci(trade_returns_clean, n_boot=5000, rng=np.random.default_rng(cfg.random_state))

    # Regime breakdown
    regimes = {
        "high_vol": feats["vol_regime"] > feats["vol_regime"].median(),
        "low_vol": feats["vol_regime"] <= feats["vol_regime"].median(),
        "high_spread": feats["spread_bps"] > feats["spread_bps"].median(),
        "low_spread": feats["spread_bps"] <= feats["spread_bps"].median(),
        "high_intensity": feats["trade_intensity"] > feats["trade_intensity"].median(),
        "low_intensity": feats["trade_intensity"] <= feats["trade_intensity"].median(),
    }
    regime_results = {}
    n_positive_regimes = 0
    for name, mask in regimes.items():
        rm = mask.values
        if rm.sum() > 0:
            r_rets = np.where(trade_mask & rm, returns - costs, np.nan)
            r_rets = r_rets[~np.isnan(r_rets)]
            if len(r_rets) > 0:
                mean_ret = float(np.mean(r_rets))
                regime_results[name] = {"mean_ret_bps": mean_ret, "n": int(len(r_rets)), "positive": mean_ret > 0}
                if mean_ret > 0:
                    n_positive_regimes += 1

    # AUC
    auc = 0.5
    if len(set(target)) > 1:
        from sklearn.metrics import roc_auc_score
        try:
            auc = float(roc_auc_score(target, probs))
        except Exception:
            pass

    forward_result = {
        "experiment": "V14",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "COMPLETE",
        "forward_data_dir": cfg.forward_data_dir,
        "n_events": n,
        "n_signals": int(trade_mask.sum()),
        "n_trades": int(trade_mask.sum()),
        "auc": auc,
        "gross_ev_bps": gross_ev,
        "fees_bps": float(sim._cfg.taker_fee_bps) * trade_mask.sum() / n if n else 0,
        "maker_rebate_bps": float(sim._cfg.maker_rebate_bps) * sim._cfg.maker_fill_probability * trade_mask.sum() / n if n else 0,
        "spread_cost_bps": float(feats["spread_bps"].mean()) if len(feats) else 0,
        "slippage_cost_bps": float(sim._cfg.slippage_bps) * 2,
        "adverse_selection_bps": float(sim._cfg.adverse_selection_bps) * 2,
        "latency_cost_bps": float(sim._cfg.latency_bps) * 2,
        "total_cost_bps": float(sim.total_roundtrip_cost_bps),
        "net_ev_bps": net_ev,
        "ci_lower_bps": stat["ci_lower_bps"],
        "ci_upper_bps": stat["ci_upper_bps"],
        "p_value": stat["p_value"],
        "tstat": stat["tstat"],
        "n_traded": int(len(trade_returns_clean)),
        "regime_breakdown": regime_results,
        "positive_regimes": n_positive_regimes,
        "total_regimes": len(regimes),
        "elapsed_s": round(time.time() - t0, 2),
        "breakeven_cost_bps": breakeven_cost,
        "forward_pass": net_ev > 0 and stat["ci_lower_bps"] > 0 and stat["p_value"] < 0.05 and n_positive_regimes >= 4,
    }
    Path("data/evidence/v14_forward_validation.json").write_text(json.dumps(forward_result, indent=2, default=str))
    return forward_result


def run_pipeline(mode: str = "calibrate", config: V14Config | None = None) -> dict:
    cfg = config or V14Config()
    if mode == "calibrate":
        return calibrate(cfg)
    elif mode == "forward":
        return forward(cfg)
    else:
        raise ValueError(f"Unknown mode: {mode}")
