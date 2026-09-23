"""V12 paper trading runtime — live Binance BTCUSDT data, simulated execution.

Runs the FROZEN V12 model against live market data WITHOUT sending live orders.
All fills are simulated against the live order book. Uses the SAME frozen model
intended for production (Rule 26): no tuning during paper trading.

Components wired:
    BinanceMarketFeed -> V12LiveBook -> V12SignalEngine -> V12ExecutionModel
      -> V12RiskEngine -> V12PositionEngine -> V12OrderManager -> V12ExitEngine
      -> V12AuditLog + trade journal
"""
from __future__ import annotations

import json
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

from .config import V12Config
from .model import V12SignalModel
from .execution_model import V12ExecutionModel
from .risk import V12RiskEngine, V12RiskConfig, RiskState
from .position import V12PositionEngine, PositionSide
from .orders import V12OrderManager, V12Order, OrderStatus, OrderType
from .exit import V12ExitEngine, V12ExitConfig
from .audit import V12AuditLog
from .monitoring import V12Monitor
from .funding import fetch_current_funding, average_funding_rate_during, fetch_and_cache
from app.models import DepthEvent, TradeEvent
from app.orderbook import LocalOrderBook
from app.v11.parser import BookSnapshot, TradeRecord


USER_AGENT = "Mozilla/5.0 (compatible; V12-PaperTrading/1.0)"


@dataclass
class V12PaperConfig:
    symbol: str = "BTCUSDT"
    ws_base: str = "wss://fstream.binance.com"
    rest_base: str = "https://fapi.binance.com"
    decision_interval_ms: int = 500
    max_backoff_s: float = 30.0
    funding_cache_path: str = "archive/v12/paper_funding_cache.json"
    audit_log_path: str = "archive/v12/paper_audit.jsonl"
    journal_path: str = "data/research/v12/paper_trades.jsonl"
    snapshot_interval: int = 30


class V12LiveBook:
    """Live order-book maintained from REST snapshot + diff-depth stream.

    Produces BookSnapshot objects (compatible with v11 feature extractor) at
    each depth update, maintaining causal trade buffers.
    """

    def __init__(self, symbol: str, rest_base: str = "https://fapi.binance.com"):
        self.symbol = symbol.upper()
        self.rest_base = rest_base
        self._lock = threading.RLock()
        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}
        self.last_update_id: int | None = None
        self.synchronized = False
        self.last_depth_event_ms: int = 0
        self.last_receive_ns: int = 0
        self.trade_buffer: list[TradeRecord] = []
        self._prev_ofi_bid_l1: float = 0.0
        self._prev_ofi_ask_l1: float = 0.0
        self._prev_bids: dict[float, float] = {}
        self._prev_asks: dict[float, float] = {}
        self._depth_gap_count = 0
        self._reconnect_count = 0

    def fetch_snapshot(self) -> dict[str, Any]:
        r = requests.get(
            f"{self.rest_base}/fapi/v1/depth",
            params={"symbol": self.symbol, "limit": 1000},
            headers={"User-Agent": USER_AGENT},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()

    def load_snapshot(self, snap: dict[str, Any]) -> None:
        with self._lock:
            self.bids = {float(p): float(q) for p, q in snap["bids"] if float(q) > 0}
            self.asks = {float(p): float(q) for p, q in snap["asks"] if float(q) > 0}
            self.last_update_id = int(snap["lastUpdateId"])
            self.synchronized = False
            self._prev_bids = dict(self.bids)
            self._prev_asks = dict(self.asks)

    def apply_depth(self, e: DepthEvent) -> str:
        with self._lock:
            if self.last_update_id is None:
                return "NO_SNAPSHOT"
            if e.final_update_id <= self.last_update_id:
                return "STALE"
            if self.synchronized:
                hole = e.first_update_id - self.last_update_id - 1
                if hole > 5000:
                    self.synchronized = False
                    self._depth_gap_count += 1
                    return "GAP"
            for p, q in e.bids:
                if q == 0:
                    self.bids.pop(p, None)
                else:
                    self.bids[p] = q
            for p, q in e.asks:
                if q == 0:
                    self.asks.pop(p, None)
                else:
                    self.asks[p] = q
            self.last_update_id = e.final_update_id
            self.last_depth_event_ms = e.ts_ms
            self.last_receive_ns = time.time_ns()
            self.synchronized = True
            return "OK"

    def add_trade(self, t: TradeEvent) -> None:
        with self._lock:
            side = "SELL" if t.buyer_is_maker else "BUY"
            self.trade_buffer.append(TradeRecord(
                ts_ms=t.ts_ms, price=t.price, qty=t.qty,
                aggressor_side=side, buyer_is_maker=t.buyer_is_maker,
            ))

    def _book_snapshot(self, ts_ms: int, window_ms: int = 1000) -> BookSnapshot | None:
        with self._lock:
            if not self.synchronized or not self.bids or not self.asks:
                return None
            top_b = sorted(self.bids.items(), reverse=True)[:10]
            top_a = sorted(self.asks.items())[:10]
            best_bid = top_b[0][0]
            best_ask = top_a[0][0]
            mid = (best_bid + best_ask) / 2.0
            spread_bps = (best_ask - best_bid) / mid * 1e4
            bid_l1 = sum(q for _, q in top_b[:1])
            ask_l1 = sum(q for _, q in top_a[:1])
            bid_l5 = sum(q for _, q in top_b[:5])
            ask_l5 = sum(q for _, q in top_a[:5])
            bid_l10 = sum(q for _, q in top_b[:10])
            ask_l10 = sum(q for _, q in top_a[:10])

            cur_bids = {p: q for p, q in top_b}
            cur_asks = {p: q for p, q in top_a}
            adds = cancels = net = 0.0
            for p, q in cur_bids.items():
                old = self._prev_bids.get(p, 0.0)
                d = q - old
                if q > 0 and old == 0:
                    adds += q
                elif q == 0 and old > 0:
                    cancels += old
                net += d
            for p, q in cur_asks.items():
                old = self._prev_asks.get(p, 0.0)
                d = q - old
                if q > 0 and old == 0:
                    adds += q
                elif q == 0 and old > 0:
                    cancels += old
                net -= d
            self._prev_bids = dict(cur_bids)
            self._prev_asks = dict(cur_asks)

            ofi_l1 = bid_l1 - ask_l1
            ofi_l5 = bid_l5 - ask_l5
            ofi_l10 = bid_l10 - ask_l10
            d1 = bid_l1 + ask_l1
            qi1 = (bid_l1 - ask_l1) / d1 if d1 else 0.0
            qi5 = (bid_l5 - ask_l5) / (bid_l5 + ask_l5) if (bid_l5 + ask_l5) else 0.0
            qi10 = (bid_l10 - ask_l10) / (bid_l10 + ask_l10) if (bid_l10 + ask_l10) else 0.0

            window_start = ts_ms - window_ms
            w_trades = [t for t in self.trade_buffer if t.ts_ms >= window_start]
            w_buy = sum(t.qty for t in w_trades if t.aggressor_side == "BUY")
            w_sell = sum(t.qty for t in w_trades if t.aggressor_side == "SELL")
            w_tot = w_buy + w_sell
            tfi = (w_buy - w_sell) / w_tot if w_tot else 0.0

            while self.trade_buffer and self.trade_buffer[0].ts_ms < ts_ms - 10 * window_ms:
                self.trade_buffer.pop(0)

            return BookSnapshot(
                ts_ms=ts_ms,
                best_bid=best_bid,
                best_ask=best_ask,
                mid=mid,
                spread_bps=spread_bps,
                bids=dict(self.bids),
                asks=dict(self.asks),
                bid_depth1=bid_l1, ask_depth1=ask_l1,
                bid_depth5=bid_l5, ask_depth5=ask_l5,
                bid_depth10=bid_l10, ask_depth10=ask_l10,
                qi1=qi1, qi5=qi5, qi10=qi10,
                ofi_l1=ofi_l1, ofi_l5=ofi_l5, ofi_l10=ofi_l10,
                adds=adds, cancels=cancels, net=net,
                buy_vol=w_buy, sell_vol=w_sell, tfi=tfi,
            )

    def state_dict(self) -> dict[str, Any]:
        return {
            "synchronized": self.synchronized,
            "last_update_id": self.last_update_id,
            "best_bid": max(self.bids) if self.bids else None,
            "best_ask": min(self.asks) if self.asks else None,
            "depth_gap_count": self._depth_gap_count,
            "reconnect_count": self._reconnect_count,
        }


class V12PaperRuntime:
    """Paper-trading runtime: live data, simulated fills, frozen model."""

    def __init__(
        self,
        model: V12SignalModel,
        config: V12Config | None = None,
        paper_cfg: V12PaperConfig | None = None,
    ):
        self.config = config or V12Config()
        self.paper_cfg = paper_cfg or V12PaperConfig()
        self.book = V12LiveBook(self.config.symbol)
        self.execution_model = V12ExecutionModel(config=self.config)
        self.risk_engine = V12RiskEngine(V12RiskConfig())
        self.position_engine = V12PositionEngine(self.config)
        self.order_manager = V12OrderManager()
        self.exit_engine = V12ExitEngine(V12ExitConfig())
        self.model = model
        self.monitor = V12Monitor(
            alert_path=Path(self.paper_cfg.audit_log_path).parent / "paper_alerts.jsonl",
        )
        self._audit: V12AuditLog | None = None
        self._journal_path = Path(self.paper_cfg.journal_path)
        self._journal_path.parent.mkdir(parents=True, exist_ok=True)
        self._running = False
        self._stop_flag = False
        self._funding_points: list[Any] = []
        self._last_decision_ms = 0
        self._signal_id_counter = 0
        self._book_lock = threading.RLock()

    def _audit_log(self) -> V12AuditLog:
        if self._audit is None:
            self._audit = V12AuditLog(self.paper_cfg.audit_log_path)
        return self._audit

    def _journal_append(self, record: dict[str, Any]) -> None:
        with open(self._journal_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True, default=str) + "\n")

    def _fetch_funding_for_window(self, ts_ms: int) -> float:
        if not self._funding_points:
            return 0.0
        return average_funding_rate_during(
            self._funding_points, ts_ms, ts_ms + int(self.config.max_holding_hours * 3600_000)
        )

    def _on_depth_update(self, e: DepthEvent) -> None:
        status = self.book.apply_depth(e)
        self.monitor.update_market_data(
            depth_update_ms=e.ts_ms, trade_ms=self.book.last_depth_event_ms,
            receive_ns=self.book.last_receive_ns,
            gap=(status == "GAP"), reconnect=False, sequence_error=(status == "GAP"),
        )
        if status in ("GAP", "NO_SNAPSHOT"):
            self.risk_engine.on_api_error()
            if status == "GAP":
                self.risk_engine._state.state = RiskState.HALT
                self.risk_engine._state.halt_reason = __import__("app.v12.risk", fromlist=["HaltReason"]).HaltReason.STALE_DATA
            return
        self._maybe_decide()

    def _on_trade(self, t: TradeEvent) -> None:
        self.book.add_trade(t)

    def _maybe_decide(self) -> None:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        if now_ms - self._last_decision_ms < self.paper_cfg.decision_interval_ms:
            return
        self._last_decision_ms = now_ms
        self._run_decision_cycle(now_ms)

    def _run_decision_cycle(self, now_ms: int) -> None:
        snap = self.book._book_snapshot(now_ms, window_ms=self.config.feature_window_ms)
        if snap is None or snap.mid is None or snap.mid <= 0:
            self.monitor.update_book(age_ms=60000, crossed=False)
            return

        book_age = now_ms - snap.ts_ms
        self.monitor.update_book(age_ms=book_age, crossed=(snap.best_bid >= snap.best_ask))

        ts_ms = snap.ts_ms
        if not self._funding_points:
            try:
                self._funding_points = fetch_and_cache(
                    symbol=self.config.symbol,
                    start_ms=now_ms - 8 * 3600_000,
                    end_ms=now_ms,
                    cache_path=self.paper_cfg.funding_cache_path,
                )
            except Exception:
                self._funding_points = []

        funding_rate = self._fetch_funding_for_window(ts_ms)

        rows = [snap.__dict__]
        df = pd.DataFrame(rows)
        from app.v11.features import extract_v11_features
        feat_df = extract_v11_features([snap], self.book.trade_buffer, window_ms=self.config.signal_horizon_ms)
        if feat_df.empty:
            return
        feature_cols = [c for c in self.model._feature_names if c in feat_df.columns]
        X = feat_df[feature_cols].replace([np.inf, -np.inf], 0.0).fillna(0.0)
        try:
            probs = self.model.predict_proba(X)
            pred_rets = self.model.predict_returns(X)
        except RuntimeError:
            self.monitor.update_model(loaded=False, checksum_ok=False)
            return
        prob = float(probs[0])
        pred_ret = float(pred_rets[0])

        spread_bps = float(snap.spread_bps) if snap.spread_bps is not None else 0.013
        econ = self.execution_model.decompose_trade(
            signal_edge_bps=pred_ret,
            funding_rate_8h=funding_rate,
            hold_duration_hours=self.config.max_holding_hours,
            signal_confidence=prob,
            spread_bps=spread_bps,
        )

        features_dict = {k: float(v) for k, v in feat_df.iloc[0].items() if k in self.model._feature_names}
        self._audit_log().log_signal(
            ts_ms=ts_ms,
            market_state=self.book.state_dict(),
            features=features_dict,
            model_version="V12-frozen",
            model_output={"prob": prob, "predicted_return_bps": pred_ret},
            expected_gross_bps=econ.gross_ev_bps,
            estimated_costs_bps=econ.total_cost_bps,
            expected_net_bps=econ.net_ev_bps,
        )
        self.monitor.update_model(loaded=self.model._is_fitted, checksum_ok=True)

        signal_id = f"sig-{self._signal_id_counter:08d}"
        self._signal_id_counter += 1
        self.monitor.record_signal(positive=(prob > 0.5))

        decision = "NO_TRADE"
        reason = "below expected-net-return threshold"
        if econ.net_ev_bps > self.config.funding_threshold_bps and prob > 0.55:
            side = "BUY" if pred_ret > 0 else "SELL"
            allowed, rreason = self.risk_engine.check_pre_trade(
                side=side, qty_btc=self.config.position_size_btc, price=snap.mid,
                spread_bps=spread_bps, latency_ms=0, vol_bps=econ.adverse_selection_bps,
            )
            if allowed and self.position_engine.is_flat():
                decision = "TRADE"
                reason = f"edge={econ.net_ev_bps:.4f}bps > threshold"
            else:
                decision = "NO_TRADE"
                reason = f"risk blocked: {rreason}"
        elif self.position_engine.position.side != PositionSide.FLAT:
            decision = "HOLD"
            reason = "holding existing position"

        self._audit_log().log_decision(
            ts_ms=ts_ms, signal_id=signal_id, decision=decision, reason=reason,
            risk_state=self.risk_engine.get_state().__dict__,
            expected_net_bps=econ.net_ev_bps, funding_rate_8h=funding_rate,
        )

        if decision == "TRADE":
            self._enter_position(signal_id, side, snap, prob, econ, funding_rate, ts_ms)

        if self.position_engine.position.side != PositionSide.FLAT:
            self._manage_open_position(snap, prob, econ, funding_rate, ts_ms)

    def _enter_position(self, signal_id: str, side: str, snap: BookSnapshot, prob: float, econ, funding_rate: float, ts_ms: int) -> None:
        price = snap.best_ask if side == "BUY" else snap.best_bid
        client_id = f"v12-{int(datetime.now(timezone.utc).timestamp() * 1000)}-{self.order_manager._seq + 1}"
        order = self.order_manager.create_order(
            client_id=client_id, side=side, qty_btc=self.config.position_size_btc,
            price=price, order_type=OrderType.MARKET, reduce_only=False,
            expected_edge_bps=econ.net_ev_bps,
        )
        if order is None:
            return
        self.order_manager.submit(order.order_id)
        self.order_manager.acknowledge(order.order_id, exchange_id=f"paper-{order.order_id}")
        actual_fill_price = price
        fees_bps = self.config.taker_fee_bps
        slippage_bps = self.config.slippage_bps
        self.order_manager.fill(
            order.order_id, fill_price=actual_fill_price, fill_qty=order.qty_btc,
            fees_bps=fees_bps, slippage_bps=slippage_bps,
        )
        self._audit_log().log_order(
            order_id=order.order_id, client_id=order.client_id, exchange_id=order.exchange_id,
            side=order.side, qty_btc=order.qty_btc, price=price,
            order_type=order.order_type.value, reduce_only=order.reduce_only, expected_edge_bps=order.expected_edge_bps,
        )
        self._audit_log().log_fill(
            ts_ms=ts_ms, order_id=order.order_id, fill_price=actual_fill_price,
            fill_qty=order.qty_btc, fees_bps=fees_bps, slippage_bps=slippage_bps,
            latency_ms=0, funding_rate_8h=funding_rate, funding_income_bps=0.0,
        )
        self.monitor.update_execution(submitted=True, filled=True, latency_ms=0, spread_bps=float(snap.spread_bps or 0.013))

        entry_price = actual_fill_price
        if side == "BUY":
            sl_price = entry_price * (1 - self.config.stop_loss_bps / 1e4)
            tp_price = entry_price * (1 + self.config.take_profit_bps / 1e4)
        else:
            sl_price = entry_price * (1 + self.config.stop_loss_bps / 1e4)
            tp_price = entry_price * (1 - self.config.take_profit_bps / 1e4)
        self.position_engine.on_entry(
            side=side, qty_btc=order.qty_btc, price=entry_price, ts_ms=ts_ms,
            funding_rate=funding_rate, stop_loss=sl_price, take_profit=tp_price,
            max_hold_hours=self.config.max_holding_hours,
        )
        self._journal_append({
            "event": "ENTRY", "order_id": order.order_id, "side": side,
            "price": entry_price, "qty_btc": order.qty_btc, "ts_ms": ts_ms,
            "signal_id": signal_id, "funding_rate_8h": funding_rate,
            "expected_net_bps": econ.net_ev_bps,
        })

    def _manage_open_position(self, snap: BookSnapshot, prob: float, econ, funding_rate: float, ts_ms: int) -> None:
        position = self.position_engine.position
        mark_price = snap.mid
        self.position_engine.update_unrealized(mark_price, funding_rate)
        should_exit, reason, urgency, details = self._eval_exit(snap, prob, econ, ts_ms)
        if should_exit:
            self._exit_position(reason, snap, funding_rate, ts_ms)

    def _eval_exit(self, snap: BookSnapshot, prob: float, econ, ts_ms: int) -> tuple[bool, str, str, str]:
        position = self.position_engine.position
        decision = self.exit_engine.evaluate(
            position_side=position.side.value,
            entry_price=position.entry_price,
            mark_price=snap.mid,
            entry_ts_ms=position.entry_ts_ms,
            max_hold_ts_ms=position.max_hold_ts_ms,
            stop_loss_price=position.stop_loss_price,
            take_profit_price=position.take_profit_price,
            current_edge_bps=econ.net_ev_bps,
            adverse_selection_bps=econ.adverse_selection_bps,
            spread_bps=float(snap.spread_bps or 0.013),
            depth_usd=0.0,
            funding_rate=funding_rate,
            ts_ms=ts_ms,
        )
        return decision.should_exit, decision.reason.value, decision.urgency, decision.details

    def _exit_position(self, reason: str, snap: BookSnapshot, funding_rate: float, ts_ms: int) -> None:
        position = self.position_engine.position
        if position.side == PositionSide.FLAT:
            return
        side = "SELL" if position.side == PositionSide.LONG else "BUY"
        price = snap.best_bid if side == "SELL" else snap.best_ask
        client_id = f"v12-exit-{int(datetime.now(timezone.utc).timestamp() * 1000)}-{self.order_manager._seq + 1}"
        order = self.order_manager.create_order(
            client_id=client_id, side=side, qty_btc=position.qty_btc,
            price=price, order_type=OrderType.MARKET, reduce_only=True,
            expected_edge_bps=0.0,
        )
        self.order_manager.submit(order.order_id)
        self.order_manager.acknowledge(order.order_id, exchange_id=f"paper-exit-{order.order_id}")
        self.order_manager.fill(order.order_id, fill_price=price, fill_qty=position.qty_btc, fees_bps=self.config.taker_fee_bps, slippage_bps=self.config.slippage_bps)
        realized_pnl = self.position_engine.on_exit(exit_price=price, exit_ts_ms=ts_ms)
        self._journal_append({
            "event": "EXIT", "reason": reason, "price": price,
            "realized_pnl_bps": realized_pnl, "ts_ms": ts_ms,
            "funding_accrued_bps": position.funding_accrued_bps,
        })
        risk_state = self.risk_engine.get_state()
        if realized_pnl < 0:
            self.risk_engine.on_fill(side=side, qty_btc=position.qty_btc, pnl_bps=realized_pnl)
        else:
            self.risk_engine.on_fill(side=side, qty_btc=position.qty_btc, pnl_bps=realized_pnl)

    def run_snapshot_loop(self, duration_seconds: int) -> None:
        """Run paper trading against live Binance data for a bounded duration."""
        self._running = True
        self._stop_flag = False
        self._start_time = time.monotonic()
        end_time = self._start_time + duration_seconds
        import websocket

        streams = [
            f"{self.config.symbol.lower()}@depth",
            f"{self.config.symbol.lower()}@trade",
            f"{self.config.symbol.lower()}@bookTicker",
        ]
        ws_url = f"{self.paper_cfg.ws_base}/stream?streams={'/'.join(streams)}"

        snap = self.book.fetch_snapshot()
        self.book.load_snapshot(snap)

        def on_message(ws, raw):
            try:
                msg = json.loads(raw)
            except Exception:
                return
            data = msg.get("data", {})
            ev = data.get("e")
            if ev == "depthUpdate":
                e = DepthEvent(
                    int(data.get("E", 0)), int(data.get("U", 0)), int(data.get("u", 0)),
                    [(float(p), float(q)) for p, q in data.get("b", [])],
                    [(float(p), float(q)) for p, q in data.get("a", [])],
                )
                self._on_depth_update(e)
            elif ev in ("aggTrade", "trade"):
                self._on_trade(TradeEvent(
                    int(data.get("T", 0)), int(data.get("a", data.get("t", 0))),
                    float(data.get("p", 0)), float(data.get("q", 0)), bool(data.get("m", False)),
                ))
            if time.monotonic() >= end_time:
                ws.close()

        def on_error(ws, err):
            self.book._reconnect_count += 1
            self.risk_engine.on_api_error()
            self.monitor.update_api_error()
            if self.book._depth_gap_count > 0:
                from .risk import HaltReason
                self.risk_engine._state.state = RiskState.HALT
                self.risk_engine._state.halt_reason = HaltReason.STALE_DATA

        def on_close(ws, *args):
            self._running = False

        ws = websocket.WebSocketApp(
            ws_url, on_message=on_message, on_error=on_error, on_close=on_close,
        )
        try:
            ws.run_forever(ping_interval=20, ping_timeout=10)
        finally:
            if self._audit:
                self._audit.close()
            self._write_summary()

    def _write_summary(self) -> None:
        result = self._forward_result_placeholder()
        out = Path(self.paper_cfg.audit_log_path).parent / "paper_summary.json"
        out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    def _forward_result_placeholder(self) -> dict[str, Any]:
        pm = self.risk_engine.get_state()
        pos = self.position_engine.position
        return {
            "status": "COMPLETED",
            "duration_ms": int((time.monotonic() - getattr(self, "_start_time", time.monotonic())) * 1000),
            "position_side": pos.side.value,
            "position_qty_btc": pos.qty_btc,
            "realized_pnl_bps": pos.realized_pnl_bps,
            "unrealized_pnl_bps": pos.unrealized_pnl_bps,
            "funding_accrued_bps": pos.funding_accrued_bps,
            "risk_state": pm.state.value,
            "daily_pnl_bps": pm.daily_pnl_bps,
            "orders_submitted": self.order_manager._seq,
            "alerts": [a.__dict__ for a in self.monitor.alerts()],
        }
