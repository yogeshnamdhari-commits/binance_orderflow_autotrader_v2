"""V14 paper trading runtime — consumes live market data, generates signals
using the frozen artifact, simulates execution, records decisions, never
submits real orders.

Rule 15: Only enabled if ALL scientific gates pass. Otherwise BLOCKED.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from datetime import datetime, timezone

import numpy as np

from app.v14.config import V14Config
from app.v14.features import extract_v14_features, V14_FEATURES
from app.v14.model import V14SignalModel
from app.v14.execution import V14ExecutionSim


class V14PaperTrader:
    def __init__(self, config: V14Config, frozen_model_path: Path):
        self._cfg = config
        self._model = V14SignalModel.load(frozen_model_path)
        self._sim = V14ExecutionSim(config)
        self._decisions = []
        self._rejected = []
        self._total_cost_bps = 0.0
        self._total_edge_bps = 0.0
        self._n_trades = 0
        self._running = False

    def start(self):
        self._running = True
        print("V14 PAPER TRADING STARTED — no real orders submitted")
        print(f"  Model: {self._cfg.experiment_id}")
        print(f"  Entry cost: {self._sim.entry_cost_bps:.2f} bps")
        print(f"  Total roundtrip cost: {self._sim.total_roundtrip_cost_bps:.2f} bps")

    def stop(self):
        self._running = False
        result = {
            "experiment": "V14",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "n_trades": self._n_trades,
            "total_edge_bps": round(self._total_edge_bps, 4),
            "total_cost_bps": round(self._total_cost_bps, 4),
            "net_ev_bps": round(self._total_edge_bps - self._total_cost_bps, 4) if self._n_trades > 0 else 0.0,
            "decisions": self._decisions,
            "rejected": self._rejected,
            "live_order_submitted": False,
        }
        Path("archive/v14/v14_paper_trading_result.json").write_text(json.dumps(result, indent=2, default=str))
        return result

    def process_tick(self, books: list, trades: list):
        """Process a single tick: extract features, generate signal, simulate."""
        feats = extract_v14_features(books, trades, self._cfg.feature_window_ms)
        if len(feats) == 0:
            return None
        latest = feats.iloc[-1]
        X = feats[V14_FEATURES].copy().replace([np.inf, -np.inf], 0.0).fillna(0.0)
        probs = self._model.predict_proba(X)
        pred_returns = self._model.predict_returns(X)
        prob = probs[-1]
        pred_return = pred_returns[-1]
        breakeven = self._sim.total_roundtrip_cost_bps

        if np.abs(pred_return) > breakeven:
            entry_cost = self._sim.entry_cost_bps
            exit_cost = self._cfg.exit_cost_bps
            net = pred_return - entry_cost - exit_cost
            decision = {
                "timestamp_ns": int(time.time() * 1e9),
                "ts_ms": int(latest["ts_ms"]),
                "mid": float(latest["mid"]),
                "probability_long": round(float(prob), 4),
                "expected_return_bps": round(float(pred_return), 4),
                "entry_cost_bps": round(float(entry_cost), 4),
                "exit_cost_bps": round(float(exit_cost), 4),
                "net_expected_bps": round(float(net), 4),
                "action": "LONG" if pred_return > 0 else "SHORT",
                "simulation": "MAKER_QUEUE" if self._cfg.maker_fill_probability > 0.5 else "TAKER",
                "live_order_submitted": False,
            }
            self._decisions.append(decision)
            self._total_edge_bps += float(pred_return)
            self._total_cost_bps += float(entry_cost + exit_cost)
            self._n_trades += 1
            print(f"  SIGNAL: {decision['action']} prob={prob:.4f} exp_ret={pred_return:.2f}bps net={net:.2f}bps")
            return decision
        else:
            self._rejected.append({
                "timestamp_ns": int(time.time() * 1e9),
                "ts_ms": int(latest["ts_ms"]),
                "prob": round(float(prob), 4),
                "pred_return": round(float(pred_return), 4),
                "reason": "below_breakeven_threshold",
            })
            return None

    def get_summary(self) -> dict:
        return {
            "n_decisions": self._n_trades,
            "total_edge_bps": round(self._total_edge_bps, 4),
            "total_cost_bps": round(self._total_cost_bps, 4),
            "live_order_submitted": False,
        }
