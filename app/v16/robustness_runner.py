"""Build reproducible V16 trade-level evidence and run fixed robustness gates."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from app.v16.config import V16Config
from app.v16.execution import V16ExecutionSim
from app.v16.model import V16FillProbabilityModel, V16ReturnModel
from app.v16.pipeline import _make_feature_target
from app.v16.robustness import evaluate_robustness


def _market_state(row: pd.Series, vol_median: float, liq_median: float, spread_median: float) -> str:
    vol = "high_vol" if row["vol_regime"] > vol_median else "low_vol"
    liq = "high_liq" if row["liquidity_state"] > liq_median else "low_liq"
    spread = "tight_spread" if row["spread_bps"] < spread_median else "wide_spread"
    return f"{vol}|{liq}|{spread}"


def run(config: V16Config | None = None) -> dict:
    cfg = config or V16Config()
    return_model = V16ReturnModel.load(Path(cfg.archive_dir) / "v16_frozen_return_model.joblib")
    fill_model = V16FillProbabilityModel.load(Path(cfg.archive_dir) / "v16_frozen_fill_model.joblib")
    feats = _make_feature_target(cfg.forward_data_dir, cfg.prediction_horizon_ms)
    if len(feats) < cfg.min_observations_forward:
        return {"status": "BLOCKED", "reason": "insufficient forward observations"}

    pred = return_model.predict(feats)
    fill = fill_model.predict_proba(feats)
    sim = V16ExecutionSim(cfg)
    decisions = [sim.route(pr, fp) for pr, fp in zip(pred, fill)]
    trade_idx = [i for i, d in enumerate(decisions) if d.action in ("MAKER", "TAKER")]
    if len(trade_idx) < 100:
        return {"status": "BLOCKED", "reason": f"insufficient forward trades: {len(trade_idx)} < 100"}

    trade_feats = feats.iloc[trade_idx].reset_index(drop=True)
    vol_med = float(trade_feats["vol_regime"].median())
    liq_med = float(trade_feats["liquidity_state"].median())
    spread_med = float(trade_feats["spread_bps"].median())

    rows = []
    for j, i in enumerate(trade_idx):
        d = decisions[i]
        rows.append({
            "ts_ms": int(feats.iloc[i]["ts_ms"]),
            "action": d.action,
            "predicted_return_bps": float(d.predicted_return_bps),
            "fill_probability": float(d.fill_probability),
            "total_cost_bps": float(d.total_cost_bps),
            "expected_pnl_bps": float(d.expected_pnl_bps),
            "regime": _market_state(trade_feats.iloc[j], vol_med, liq_med, spread_med),
        })

    trades = pd.DataFrame(rows).sort_values("ts_ms").reset_index(drop=True)
    evidence_dir = Path("data/evidence")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    trades_path = evidence_dir / "v16_forward_trades.json"
    trades.to_json(trades_path, orient="records", indent=2)

    result = evaluate_robustness(trades)
    result.update({
        "experiment": "V16",
        "source": "frozen_forward_model_on_forward_data",
        "trade_evidence_path": str(trades_path),
    })
    (evidence_dir / "v16_robustness.json").write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
