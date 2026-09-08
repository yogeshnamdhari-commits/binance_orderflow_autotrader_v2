"""V16 paper trading runtime — consumes live market data, generates signals
using the frozen artifacts, simulates execution, records decisions, never
submits real orders.

Rule 15: Only enabled if ALL scientific gates pass. Otherwise BLOCKED.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Literal

import numpy as np
import pandas as pd

from app.v16.config import V16Config
from app.v16.features import extract_v16_features, V16_FEATURES
from app.v16.model import V16ReturnModel, V16FillProbabilityModel
from app.v16.execution import V16ExecutionSim, V16ExecutionDecision


class V16PaperPosition:
    def __init__(self, symbol: str, side: Literal["LONG", "SHORT"], entry_price: float,
                 qty: float, entry_cost_bps: float, entry_ts_ms: int):
        self.symbol = symbol
        self.side = side
        self.entry_price = entry_price
        self.qty = qty
        self.avg_price = entry_price
        self.entry_cost_bps = entry_cost_bps
        self.entry_ts_ms = entry_ts_ms
        self.realized_pnl_bps = 0.0
        self.unrealized_pnl_bps = 0.0
        self.fees_paid = entry_cost_bps * qty * entry_price / 1e4
        self.status: Literal["OPEN", "CLOSED"] = "OPEN"

    def update_unrealized(self, current_mid: float):
        if self.side == "LONG":
            ret_bps = (current_mid - self.avg_price) / self.avg_price * 1e4
        else:
            ret_bps = (self.avg_price - current_mid) / self.avg_price * 1e4
        self.unrealized_pnl_bps = ret_bps - self.entry_cost_bps

    def close(self, exit_price: float, exit_cost_bps: float, exit_ts_ms: int):
        if self.side == "LONG":
            ret_bps = (exit_price - self.avg_price) / self.avg_price * 1e4
        else:
            ret_bps = (self.avg_price - exit_price) / self.avg_price * 1e4
        self.realized_pnl_bps = ret_bps - self.entry_cost_bps - exit_cost_bps
        self.fees_paid += exit_cost_bps * self.qty * exit_price / 1e4
        self.status = "CLOSED"


class V16PaperTrader:
    def __init__(self, config: V16Config, return_model_path: Path, fill_model_path: Path):
        self._cfg = config
        self._return_model = V16ReturnModel.load(return_model_path)
        self._fill_model = V16FillProbabilityModel.load(fill_model_path)
        self._sim = V16ExecutionSim(config)

        self._decisions: list[dict] = []
        self._rejected: list[dict] = []
        self._positions: list[V16PaperPosition] = []
        self._closed_positions: list[V16PaperPosition] = []
        self._running = False
        self._last_event_ts_ms = 0
        self._pnls: list[float] = []
        self._n_trades = 0

    def start(self):
        self._running = True
        print("V16 PAPER TRADING STARTED — no real orders submitted")
        print(f"  Model: {self._cfg.experiment_id}")
        print(f"  Maker entry cost: {self._cfg.maker_entry_cost_bps:.2f} bps")
        print(f"  Taker entry cost: {self._cfg.taker_entry_cost_bps:.2f} bps")
        print(f"  Exit cost: {self._cfg.exit_cost_bps:.2f} bps")
        print(f"  Total roundtrip cost (maker): {self._cfg.total_roundtrip_cost_bps:.2f} bps")
        print(f"  Stop loss: {self._cfg.stop_loss_bps:.1f} bps")
        print(f"  Max holding: {self._cfg.max_holding_hours:.1f} hours")

    def stop(self) -> dict:
        self._running = False
        for pos in self._positions:
            if pos.status == "OPEN":
                pos.status = "CLOSED"
                self._closed_positions.append(pos)
        total_edge = float(np.mean([d["predicted_return_bps"] for d in self._decisions])) if self._decisions else 0.0
        total_cost = float(np.mean([d["total_cost_bps"] for d in self._decisions])) if self._decisions else 0.0
        net_ev = float(np.mean(self._pnls)) if self._pnls else 0.0

        result = {
            "experiment": "V16",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "COMPLETE",
            "n_trades": self._n_trades,
            "n_decisions": len(self._decisions),
            "n_rejected": len(self._rejected),
            "total_edge_bps": round(total_edge, 4),
            "total_cost_bps": round(total_cost, 4),
            "net_ev_bps": round(net_ev, 4),
            "decisions": self._decisions,
            "rejected": self._rejected,
            "closed_positions": [
                {
                    "side": p.side,
                    "entry_price": p.entry_price,
                    "qty": p.qty,
                    "realized_pnl_bps": round(p.realized_pnl_bps, 4),
                    "fees_paid": round(p.fees_paid, 4),
                }
                for p in self._closed_positions
            ],
            "live_order_submitted": False,
            "paper_trading_passed": False,
        }
        Path("archive/v16/v16_paper_trading_result.json").write_text(json.dumps(result, indent=2, default=str))
        return result

    def process_event(self, books: list, trades: list) -> dict | None:
        if not self._running:
            return None

        if not books:
            return None

        feats = extract_v16_features(books, trades, self._cfg.feature_window_ms)
        if len(feats) == 0:
            return None

        latest_ts = int(feats["ts_ms"].iloc[-1])
        if latest_ts <= self._last_event_ts_ms:
            return None
        self._last_event_ts_ms = latest_ts

        X = feats[V16_FEATURES].copy().replace([np.inf, -np.inf], 0.0).fillna(0.0)
        pred_returns = self._return_model.predict(X)
        fill_probs = self._fill_model.predict_proba(X)

        latest_idx = -1
        pred_return = float(pred_returns[latest_idx])
        fill_prob = float(fill_probs[latest_idx])
        latest_feat = feats.iloc[latest_idx]
        mid = float(latest_feat["mid"]) if "mid" in latest_feat and latest_feat["mid"] else 0.0

        decision = self._sim.route(pred_return, fill_prob)

        if decision.action == "NONE":
            self._rejected.append({
                "ts_ms": latest_ts,
                "predicted_return_bps": round(pred_return, 4),
                "fill_probability": round(fill_prob, 4),
                "reason": decision.reason,
            })
            return None

        self._n_trades += 1
        self._pnls.append(decision.expected_pnl_bps)

        side: Literal["LONG", "SHORT"] = "LONG" if pred_return > 0 else "SHORT"
        entry_price = mid
        qty = self._cfg.position_size_btc

        position = V16PaperPosition(
            symbol=self._cfg.symbol,
            side=side,
            entry_price=entry_price,
            qty=qty,
            entry_cost_bps=decision.entry_cost_bps,
            entry_ts_ms=latest_ts,
        )
        self._positions.append(position)

        record = {
            "ts_ms": latest_ts,
            "action": decision.action,
            "side": side,
            "mid": mid,
            "predicted_return_bps": round(pred_return, 4),
            "fill_probability": round(fill_prob, 4),
            "expected_pnl_bps": round(decision.expected_pnl_bps, 4),
            "entry_cost_bps": round(decision.entry_cost_bps, 4),
            "exit_cost_bps": round(decision.exit_cost_bps, 4),
            "total_cost_bps": round(decision.total_cost_bps, 4),
            "non_fill_cost_bps": round(decision.non_fill_cost_bps, 4),
            "qty": qty,
            "entry_price": entry_price,
            "reason": decision.reason,
        }
        self._decisions.append(record)
        return record

    def update_positions(self, current_mid: float, current_ts_ms: int):
        for pos in self._positions:
            if pos.status != "OPEN":
                continue
            pos.update_unrealized(current_mid)

            holding_hours = (current_ts_ms - pos.entry_ts_ms) / 1000 / 3600
            if (pos.unrealized_pnl_bps <= -self._cfg.stop_loss_bps or
                holding_hours >= self._cfg.max_holding_hours):
                exit_cost_bps = self._cfg.exit_cost_bps
                pos.close(current_mid, exit_cost_bps, current_ts_ms)
                self._closed_positions.append(pos)
                self._positions.remove(pos)
