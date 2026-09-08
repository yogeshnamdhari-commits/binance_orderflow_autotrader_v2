"""V16 paper-trading runtime with realized-P&L accounting."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
import numpy as np
from app.v16.config import V16Config
from app.v16.features import extract_v16_features, V16_FEATURES
from app.v16.model import V16ReturnModel, V16FillProbabilityModel
from app.v16.execution import V16ExecutionSim

class V16PaperPosition:
    def __init__(self, symbol: str, side: Literal["LONG", "SHORT"], entry_price: float, qty: float, entry_cost_bps: float, entry_ts_ms: int):
        self.symbol, self.side, self.entry_price, self.qty = symbol, side, entry_price, qty
        self.avg_price, self.entry_cost_bps, self.entry_ts_ms = entry_price, entry_cost_bps, entry_ts_ms
        self.realized_pnl_bps = 0.0
        self.unrealized_pnl_bps = 0.0
        self.fees_paid = entry_cost_bps * qty * entry_price / 1e4
        self.status: Literal["OPEN", "CLOSED"] = "OPEN"
        self.exit_price = None
        self.exit_ts_ms = None
        self.exit_cost_bps = 0.0

    def update_unrealized(self, current_mid: float):
        ret_bps = ((current_mid - self.avg_price) if self.side == "LONG" else (self.avg_price - current_mid)) / self.avg_price * 1e4
        self.unrealized_pnl_bps = ret_bps - self.entry_cost_bps

    def close(self, exit_price: float, exit_cost_bps: float, exit_ts_ms: int):
        if self.status != "OPEN":
            return
        ret_bps = ((exit_price - self.avg_price) if self.side == "LONG" else (self.avg_price - exit_price)) / self.avg_price * 1e4
        self.realized_pnl_bps = ret_bps - self.entry_cost_bps - exit_cost_bps
        self.fees_paid += exit_cost_bps * self.qty * exit_price / 1e4
        self.exit_price, self.exit_ts_ms, self.exit_cost_bps = exit_price, exit_ts_ms, exit_cost_bps
        self.unrealized_pnl_bps = 0.0
        self.status = "CLOSED"

class V16PaperTrader:
    def __init__(self, config: V16Config, return_model_path: Path, fill_model_path: Path):
        self._cfg = config
        self._return_model = V16ReturnModel.load(return_model_path)
        self._fill_model = V16FillProbabilityModel.load(fill_model_path)
        self._sim = V16ExecutionSim(config)
        self._decisions, self._rejected = [], []
        self._positions, self._closed_positions = [], []
        self._running = False
        self._last_event_ts_ms = 0
        self._last_mid = None
        self._last_ts_ms = None

    def start(self):
        self._running = True
        print("V16 PAPER TRADING STARTED — no real orders submitted")

    def _close_open_positions(self, exit_price: float, exit_ts_ms: int):
        for pos in list(self._positions):
            pos.close(exit_price, self._cfg.exit_cost_bps, exit_ts_ms)
            self._closed_positions.append(pos)
        self._positions.clear()

    def stop(self) -> dict:
        self._running = False
        if self._last_mid is not None and self._last_ts_ms is not None:
            self._close_open_positions(self._last_mid, self._last_ts_ms)
        realized = [p.realized_pnl_bps for p in self._closed_positions]
        result = {
            "experiment": "V16", "timestamp": datetime.now(timezone.utc).isoformat(), "status": "COMPLETE",
            "n_trades": len(self._closed_positions), "n_decisions": len(self._decisions), "n_rejected": len(self._rejected),
            "total_edge_bps": round(float(np.mean([d["predicted_return_bps"] for d in self._decisions])) if self._decisions else 0.0, 4),
            "decision_cost_bps": round(float(np.mean([d["total_cost_bps"] for d in self._decisions])) if self._decisions else 0.0, 4),
            "net_ev_bps": round(float(np.mean(realized)) if realized else 0.0, 4),
            "realized_pnl_bps_mean": round(float(np.mean(realized)) if realized else 0.0, 4),
            "realized_pnl_bps_sum": round(float(np.sum(realized)) if realized else 0.0, 4),
            "realized_trade_count": len(self._closed_positions), "decisions": self._decisions, "rejected": self._rejected,
            "closed_positions": [{"side": p.side, "entry_price": p.entry_price, "exit_price": p.exit_price, "qty": p.qty,
                                  "entry_ts_ms": p.entry_ts_ms, "exit_ts_ms": p.exit_ts_ms,
                                  "realized_pnl_bps": round(p.realized_pnl_bps, 4), "fees_paid": round(p.fees_paid, 8),
                                  "entry_cost_bps": p.entry_cost_bps, "exit_cost_bps": p.exit_cost_bps}
                                 for p in self._closed_positions],
            "live_order_submitted": False, "paper_trading_passed": False,
            "performance_basis": "realized_closed_trade_pnl",
        }
        Path("archive/v16/v16_paper_trading_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    def process_event(self, books: list, trades: list) -> dict | None:
        if not self._running or not books:
            return None
        feats = extract_v16_features(books, trades, self._cfg.feature_window_ms)
        if len(feats) == 0:
            return None
        latest_ts = int(feats["ts_ms"].iloc[-1])
        if latest_ts <= self._last_event_ts_ms:
            return None
        self._last_event_ts_ms = latest_ts
        X = feats[V16_FEATURES].copy().replace([np.inf, -np.inf], 0.0).fillna(0.0)
        pred_return, fill_prob = float(self._return_model.predict(X)[-1]), float(self._fill_model.predict_proba(X)[-1])
        mid = float(feats.iloc[-1]["mid"])
        if not np.isfinite(mid) or mid <= 0:
            return None
        self._last_mid, self._last_ts_ms = mid, latest_ts
        decision = self._sim.route(pred_return, fill_prob)
        if decision.action == "NONE":
            self._rejected.append({"ts_ms": latest_ts, "predicted_return_bps": round(pred_return, 4), "fill_probability": round(fill_prob, 4), "reason": decision.reason})
            return None
        side: Literal["LONG", "SHORT"] = "LONG" if pred_return > 0 else "SHORT"
        self._positions.append(V16PaperPosition(self._cfg.symbol, side, mid, self._cfg.position_size_btc, decision.entry_cost_bps, latest_ts))
        record = {"ts_ms": latest_ts, "action": decision.action, "side": side, "mid": mid,
                  "predicted_return_bps": round(pred_return, 4), "fill_probability": round(fill_prob, 4),
                  "expected_pnl_bps": round(decision.expected_pnl_bps, 4), "entry_cost_bps": round(decision.entry_cost_bps, 4),
                  "exit_cost_bps": round(decision.exit_cost_bps, 4), "total_cost_bps": round(decision.total_cost_bps, 4),
                  "non_fill_cost_bps": round(decision.non_fill_cost_bps, 4), "qty": self._cfg.position_size_btc,
                  "entry_price": mid, "reason": decision.reason}
        self._decisions.append(record)
        return record

    def update_positions(self, current_mid: float, current_ts_ms: int):
        if not np.isfinite(current_mid) or current_mid <= 0:
            return
        self._last_mid, self._last_ts_ms = float(current_mid), int(current_ts_ms)
        for pos in list(self._positions):
            if pos.status != "OPEN":
                continue
            pos.update_unrealized(current_mid)
            holding_hours = (current_ts_ms - pos.entry_ts_ms) / 1000 / 3600
            if pos.unrealized_pnl_bps <= -self._cfg.stop_loss_bps or holding_hours >= self._cfg.max_holding_hours:
                pos.close(current_mid, self._cfg.exit_cost_bps, current_ts_ms)
                self._closed_positions.append(pos)
                self._positions.remove(pos)
