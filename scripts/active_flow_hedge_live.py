"""Fail-closed live runner for ACTIVE_FLOW_HEDGE-0.1.

No order can be submitted unless the separate deployment manifest passes all
production authorization checks. This script does not alter candidate parameters.
"""

from __future__ import annotations

from collections import deque
import json
import os
from pathlib import Path
import threading
import time

import websocket

from app.mm.book import L2Snapshot, L2Update, OrderBook
from app.mm.config import V20Config
from app.mm.live_quote_engine import ActiveFlowHedgeQuoteEngine
from app.mm.live_controller import ActiveFlowHedgeLiveController
from app.mm.production_execution import (
    BinanceFuturesREST,
    ProductionExecutionGuard,
    ProductionSafetyError,
    UserDataStreamMonitor,
)


class LiveService:
    def __init__(self, config: V20Config, config_sha: str) -> None:
        self.config = config
        self.config_sha = config_sha
        self.rest = BinanceFuturesREST(
            api_key=os.environ.get("BINANCE_API_KEY", ""),
            api_secret=os.environ.get("BINANCE_API_SECRET", ""),
            base_url=os.environ.get("BINANCE_REST", "https://fapi.binance.com"),
        )
        self.guard = ProductionExecutionGuard(
            rest=self.rest,
            symbol=config.symbol,
            max_position_notional_usd=config.max_position_notional_usd,
            candidate_config_sha256=config_sha,
            research_reference_commit="a06e8f590634777bbd5ade86ef3b2563194ca2ed",
            manifest_path=os.environ.get(
                "AFH_DEPLOYMENT_MANIFEST",
                "data/live/active_flow_hedge_deployment.json",
            ),
            kill_switch_path=os.environ.get(
                "AFH_KILL_SWITCH",
                "data/live/ACTIVE_FLOW_HEDGE_KILL",
            ),
        )
        self.controller = ActiveFlowHedgeLiveController(config, self.guard)
        self.quote_engine = ActiveFlowHedgeQuoteEngine(config)
        self.book: OrderBook | None = None
        self.buffer: list[L2Update] = []
        self.flow: deque[tuple[int, float]] = deque()
        self.signed_flow = 0.0
        self.total_flow = 0.0
        self.window_ms = max(1, int(config.flow_window_ms))
        self.stop = threading.Event()

    def _snapshot(self) -> L2Snapshot:
        response = self.rest._request(
            "GET",
            "/fapi/v1/depth",
            {"symbol": self.config.symbol, "limit": 1000},
        )
        return L2Snapshot(
            timestamp_ns=int(response.get("E", time.time() * 1000)) * 1_000_000,
            last_update_id=int(response["lastUpdateId"]),
            bids=[(float(p), float(q)) for p, q in response["bids"]],
            asks=[(float(p), float(q)) for p, q in response["asks"]],
            bridge_complete=False,
        )

    def _try_bridge(self) -> bool:
        if not self.buffer:
            return False
        snapshot = self._snapshot()
        bridge_index = None
        for i, update in enumerate(self.buffer):
            if update.first_update_id <= snapshot.last_update_id <= update.final_update_id:
                bridge_index = i
                break
        if bridge_index is None:
            return False

        book = OrderBook.from_snapshot(snapshot)
        try:
            for update in self.buffer[bridge_index:]:
                book.apply_update(update)
        except ValueError:
            self.guard.trip("L2 sequence gap during snapshot bridge")
            self.book = None
            self.buffer = []
            return False

        self.book = book
        self.buffer = []
        self.guard.update_market_heartbeat(
            book.timestamp_ns // 1_000_000,
            synchronized=book.is_valid() and not book._awaiting_first_diff,
        )
        return self.book.is_valid()

    def _flow_imbalance(self) -> float:
        return self.signed_flow / self.total_flow if self.total_flow > 0 else 0.0

    def _on_trade(self, m: dict) -> None:
        ts = int(m.get("T", m.get("E", time.time() * 1000)))
        qty = max(0.0, float(m["q"]))
        signed = -qty if bool(m["m"]) else qty
        self.flow.append((ts, signed))
        self.signed_flow += signed
        self.total_flow += qty
        cutoff = ts - self.window_ms
        while self.flow and self.flow[0][0] < cutoff:
            _, old = self.flow.popleft()
            self.signed_flow -= old
            self.total_flow -= abs(old)

    def _on_depth(self, m: dict) -> None:
        update = L2Update(
            timestamp_ns=int(m["E"]) * 1_000_000,
            first_update_id=int(m["U"]),
            final_update_id=int(m["u"]),
            prev_final_update_id=int(m.get("pu", 0)),
            bids=[(float(p), float(q)) for p, q in m["b"]],
            asks=[(float(p), float(q)) for p, q in m["a"]],
        )

        if self.book is None:
            self.buffer.append(update)
            if len(self.buffer) >= 5:
                self._try_bridge()
            return

        try:
            self.book.apply_update(update)
        except ValueError:
            self.guard.trip("L2 sequence gap; market data invalid")
            self.book = None
            self.buffer = []
            return

        self.guard.update_market_heartbeat(
            update.timestamp_ns // 1_000_000, synchronized=self.book.is_valid()
        )

        if not self.book.is_valid():
            self.guard.trip("L2 book invalid")
            return

        self.guard.health_check(update.timestamp_ns // 1_000_000)
        if self.guard.state.kill_switch:
            return

        try:
            pair = self.quote_engine.build(
                book=self.book,
                inventory=self.guard.state.position_qty,
                flow_imbalance=self._flow_imbalance(),
                inventory_limit_breaches=0,
            )
            best_bid = max(self.book.bids)
            best_ask = min(self.book.asks)
            quotes = self.controller.build_quotes(
                book=self.book,
                inventory=self.guard.state.position_qty,
                flow_imbalance=self._flow_imbalance(),
                quote_size_scale=1.0,
            )
            if quotes:
                self.controller.submit(quotes, best_bid=best_bid, best_ask=best_ask)
        except ProductionSafetyError:
            return
        except Exception as exc:
            self.guard.trip(f"live quote error: {exc}")

    def on_message(self, _ws, raw: str) -> None:
        try:
            outer = json.loads(raw)
            m = outer.get("data", outer)
            event_type = m.get("e")
            if event_type == "depthUpdate":
                self._on_depth(m)
            elif event_type == "aggTrade":
                self._on_trade(m)
        except Exception as exc:
            self.guard.trip(f"market message processing failure: {exc}")

    def run(self) -> None:
        # Must complete all authorization gates before the first live submission.
        self.guard.authorize()
        user_stream = UserDataStreamMonitor(
            self.rest,
            self._on_user_event,
            ws_url_template=os.environ.get(
                "BINANCE_USER_WS_TEMPLATE",
                "wss://fstream.binance.com/private/ws/{listen_key}",
            ),
        )
        user_stream.start()

        url = os.environ.get(
            "BINANCE_MARKET_WS",
            "wss://fstream.binance.com/public/stream?streams="
            + f"{self.config.symbol.lower()}@depth@100ms/"
            + f"{self.config.symbol.lower()}@aggTrade",
        )
        app = websocket.WebSocketApp(url, on_message=self.on_message)
        try:
            app.run_forever(ping_interval=20, ping_timeout=10)
        finally:
            user_stream.stop()

    def _on_user_event(self, event: dict) -> None:
        event_type = event.get("e")
        if event_type == "ORDER_TRADE_UPDATE":
            self.guard.update_order_event(event)
        elif event_type == "ACCOUNT_UPDATE":
            self.guard.update_account_event(event)
        elif event_type == "listenKeyExpired":
            self.guard.trip("listenKey expired")


def main() -> int:
    import argparse
    from app.mm.config import config_sha256

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="app/mm/config_v21_active_flow_hedge_01bps.json")
    ap.add_argument("--preflight", action="store_true")
    args = ap.parse_args()

    config, sha = V20Config.load_authoritative(args.config)
    service = LiveService(config, sha)

    if args.preflight:
        print(f"CONFIG_SHA256={sha}")
        print("LIVE_ORDER_SUBMISSION=", config.live_order_submission)
        try:
            service.guard.authorize()
        except ProductionSafetyError as exc:
            print(f"AUTHORIZATION=BLOCKED: {exc}")
            return 2
        print("AUTHORIZATION=PASS")
        return 0

    service.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
