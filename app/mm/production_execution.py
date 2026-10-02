"""Fail-closed production execution boundary for ACTIVE_FLOW_HEDGE-0.1."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR
import hashlib
import hmac
import json
import math
from pathlib import Path
import threading
import time
from typing import Any, Callable
from urllib.parse import urlencode

import requests
import websocket


class ProductionSafetyError(RuntimeError):
    """A production safety gate prevented an unsafe action."""


class AmbiguousOrderError(RuntimeError):
    """An order response was ambiguous; reconciliation is required."""


@dataclass(frozen=True)
class SymbolRules:
    symbol: str
    tick_size: Decimal
    min_price: Decimal
    max_price: Decimal
    step_size: Decimal
    min_qty: Decimal
    max_qty: Decimal
    min_notional: Decimal = Decimal("0")
    status: str = "TRADING"

    @classmethod
    def from_exchange_info(cls, symbol: str, payload: dict[str, Any]) -> "SymbolRules":
        for row in payload.get("symbols", []):
            if row.get("symbol") != symbol:
                continue
            filters = {f.get("filterType"): f for f in row.get("filters", [])}
            pf = filters.get("PRICE_FILTER", {})
            lf = filters.get("LOT_SIZE", {})
            nf = filters.get("MIN_NOTIONAL") or filters.get("NOTIONAL") or {}
            return cls(
                symbol=symbol,
                tick_size=Decimal(str(pf.get("tickSize", "0"))),
                min_price=Decimal(str(pf.get("minPrice", "0"))),
                max_price=Decimal(str(pf.get("maxPrice", "0"))),
                step_size=Decimal(str(lf.get("stepSize", "0"))),
                min_qty=Decimal(str(lf.get("minQty", "0"))),
                max_qty=Decimal(str(lf.get("maxQty", "0"))),
                min_notional=Decimal(str(nf.get("notional", nf.get("minNotional", "0")))),
                status=str(row.get("status", "UNKNOWN")),
            )
        raise ProductionSafetyError(f"symbol {symbol} missing from exchangeInfo")

    @staticmethod
    def _positive(value: Decimal) -> bool:
        return value.is_finite() and value > 0

    def floor_qty(self, qty: float | Decimal) -> Decimal:
        try:
            value = Decimal(str(qty))
        except InvalidOperation as exc:
            raise ProductionSafetyError("invalid quantity") from exc
        if not self._positive(value) or self.step_size <= 0:
            return Decimal("0")
        return (value / self.step_size).to_integral_value(rounding=ROUND_DOWN) * self.step_size

    def floor_price(self, price: float | Decimal) -> Decimal:
        try:
            value = Decimal(str(price))
        except InvalidOperation as exc:
            raise ProductionSafetyError("invalid price") from exc
        if not self._positive(value) or self.tick_size <= 0:
            raise ProductionSafetyError("invalid price/tick")
        return (value / self.tick_size).to_integral_value(rounding=ROUND_FLOOR) * self.tick_size

    def ceil_price(self, price: float | Decimal) -> Decimal:
        try:
            value = Decimal(str(price))
        except InvalidOperation as exc:
            raise ProductionSafetyError("invalid price") from exc
        if not self._positive(value) or self.tick_size <= 0:
            raise ProductionSafetyError("invalid price/tick")
        return (value / self.tick_size).to_integral_value(rounding=ROUND_CEILING) * self.tick_size

    def validate_price(self, price: Decimal) -> None:
        if not self._positive(price):
            raise ProductionSafetyError("price must be finite and positive")
        if self.min_price > 0 and price < self.min_price:
            raise ProductionSafetyError("price below minPrice")
        if self.max_price > 0 and price > self.max_price:
            raise ProductionSafetyError("price above maxPrice")
        if self.tick_size > 0:
            units = (price / self.tick_size).to_integral_value()
            if price != units * self.tick_size:
                raise ProductionSafetyError("price violates tickSize")

    def validate_qty(self, qty: Decimal, price: Decimal) -> None:
        if not self._positive(qty):
            raise ProductionSafetyError("quantity must be finite and positive")
        if self.min_qty > 0 and qty < self.min_qty:
            raise ProductionSafetyError("quantity below minQty")
        if self.max_qty > 0 and qty > self.max_qty:
            raise ProductionSafetyError("quantity above maxQty")
        if self.step_size > 0:
            units = (qty / self.step_size).to_integral_value()
            if qty != units * self.step_size:
                raise ProductionSafetyError("quantity violates stepSize")
        if self.min_notional > 0 and qty * price < self.min_notional:
            raise ProductionSafetyError("notional below minimum")


class BinanceFuturesREST:
    """Minimal signed USDⓈ-M REST client. Never blindly retries an order POST."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = "https://fapi.binance.com",
        recv_window_ms: int = 5000,
        session: requests.Session | None = None,
    ) -> None:
        if not api_key or not api_secret:
            raise ProductionSafetyError("API credentials are required")
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url.rstrip("/")
        self.recv_window_ms = int(recv_window_ms)
        self.session = session or requests.Session()
        self.server_offset_ms = 0
        self._lock = threading.Lock()

    def sync_clock(self) -> int:
        t0 = time.time_ns() // 1_000_000
        r = self.session.get(f"{self.base_url}/fapi/v1/time", timeout=3)
        r.raise_for_status()
        t1 = time.time_ns() // 1_000_000
        server_ms = int(r.json()["serverTime"])
        midpoint = (t0 + t1) // 2
        with self._lock:
            self.server_offset_ms = server_ms - midpoint
        return self.server_offset_ms

    def _timestamp(self) -> int:
        with self._lock:
            return int(time.time() * 1000) + self.server_offset_ms

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        signed: bool = False,
    ) -> Any:
        payload = dict(params or {})
        if signed:
            payload.setdefault("recvWindow", self.recv_window_ms)
            payload["timestamp"] = self._timestamp()
            query = urlencode(payload, doseq=True)
            payload["signature"] = hmac.new(
                self.api_secret.encode(), query.encode(), hashlib.sha256
            ).hexdigest()

        try:
            response = self.session.request(
                method,
                f"{self.base_url}{path}",
                params=payload,
                headers={"X-MBX-APIKEY": self.api_key},
                timeout=5,
            )
        except requests.RequestException as exc:
            if method.upper() == "POST" and path == "/fapi/v1/order":
                raise AmbiguousOrderError(
                    "order transport failure; reconcile before retry"
                ) from exc
            raise ProductionSafetyError(f"REST transport failure: {exc}") from exc

        if method.upper() == "POST" and path == "/fapi/v1/order" and response.status_code in {502, 503, 504}:
            raise AmbiguousOrderError(
                f"ambiguous order response HTTP {response.status_code}; reconcile before retry"
            )
        if response.status_code in {418, 429}:
            raise ProductionSafetyError(
                f"Binance rate limit HTTP {response.status_code}; execution halted"
            )
        if not response.ok:
            try:
                body = response.json()
            except ValueError:
                body = response.text[:500]
            raise ProductionSafetyError(f"Binance HTTP {response.status_code}: {body}")
        try:
            return response.json()
        except ValueError as exc:
            raise ProductionSafetyError("non-JSON Binance response") from exc

    def exchange_info(self, symbol: str) -> SymbolRules:
        return SymbolRules.from_exchange_info(
            symbol, self._request("GET", "/fapi/v1/exchangeInfo")
        )

    def position_risk(self, symbol: str) -> list[dict[str, Any]]:
        data = self._request(
            "GET", "/fapi/v3/positionRisk", {"symbol": symbol}, signed=True
        )
        return data if isinstance(data, list) else [data]

    def open_orders(self, symbol: str) -> list[dict[str, Any]]:
        data = self._request(
            "GET", "/fapi/v1/openOrders", {"symbol": symbol}, signed=True
        )
        return data if isinstance(data, list) else []

    def new_post_only_limit(
        self, symbol: str, side: str, qty: Decimal, price: Decimal, client_order_id: str
    ) -> dict[str, Any]:
        if side not in {"BUY", "SELL"}:
            raise ProductionSafetyError("invalid side")
        return self._request(
            "POST",
            "/fapi/v1/order",
            {
                "symbol": symbol,
                "side": side,
                "type": "LIMIT",
                "timeInForce": "GTX",
                "quantity": format(qty, "f"),
                "price": format(price, "f"),
                "newClientOrderId": client_order_id,
            },
            signed=True,
        )

    def cancel_order(self, symbol: str, client_order_id: str) -> Any:
        return self._request(
            "DELETE",
            "/fapi/v1/order",
            {"symbol": symbol, "origClientOrderId": client_order_id},
            signed=True,
        )

    def cancel_all(self, symbol: str) -> Any:
        return self._request(
            "DELETE", "/fapi/v1/allOpenOrders", {"symbol": symbol}, signed=True
        )

    def create_listen_key(self) -> str:
        data = self._request("POST", "/fapi/v1/listenKey")
        key = data.get("listenKey") if isinstance(data, dict) else None
        if not key:
            raise ProductionSafetyError("listenKey creation failed")
        return str(key)

    def keepalive_listen_key(self, listen_key: str) -> str:
        data = self._request(
            "PUT", "/fapi/v1/listenKey", {"listenKey": listen_key}
        )
        return str(data.get("listenKey", listen_key)) if isinstance(data, dict) else listen_key


@dataclass
class ExecutionState:
    authorized: bool = False
    book_synchronized: bool = False
    user_stream_healthy: bool = False
    trade_stream_healthy: bool = False
    reconciliation_ok: bool = False
    last_market_event_ms: int = 0
    last_user_event_ms: int = 0
    last_trade_event_ms: int = 0
    position_qty: float = 0.0
    position_notional_usd: float = 0.0
    open_orders: dict[str, dict[str, Any]] = field(default_factory=dict)
    kill_switch: bool = False
    kill_reason: str = ""


@dataclass(frozen=True)
class DeploymentManifest:
    authorized: bool
    candidate_config_sha256: str
    required_research_commit: str
    forward_certification_status: str
    production_identity_status: str
    execution_authorization: str

    @classmethod
    def load(cls, path: str | Path) -> "DeploymentManifest":
        p = Path(path)
        if not p.is_file():
            raise ProductionSafetyError(f"deployment manifest missing: {p}")
        try:
            d = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ProductionSafetyError("invalid deployment manifest") from exc
        return cls(
            authorized=bool(d.get("authorized", False)),
            candidate_config_sha256=str(d.get("candidate_config_sha256", "")),
            required_research_commit=str(d.get("required_research_commit", "")),
            forward_certification_status=str(d.get("forward_certification_status", "")),
            production_identity_status=str(d.get("production_identity_status", "")),
            execution_authorization=str(d.get("execution_authorization", "")),
        )


class ProductionExecutionGuard:
    """Fail-closed order gate around the existing candidate."""

    def __init__(
        self,
        *,
        rest: BinanceFuturesREST,
        symbol: str,
        max_position_notional_usd: float,
        candidate_config_sha256: str,
        research_reference_commit: str,
        manifest_path: str | Path,
        kill_switch_path: str | Path = "data/live/ACTIVE_FLOW_HEDGE_KILL",
        max_market_stale_ms: int = 750,
        max_user_stream_stale_ms: int = 3000,
        max_open_orders: int = 2,
    ) -> None:
        self.rest = rest
        self.symbol = symbol
        if self.symbol != "BTCUSDT":
            raise ProductionSafetyError(
                f"production scope is BTCUSDT only; got {self.symbol}"
            )
        self.max_position_notional_usd = float(max_position_notional_usd)
        self.candidate_config_sha256 = candidate_config_sha256
        self.research_reference_commit = research_reference_commit
        self.manifest_path = Path(manifest_path)
        self.kill_switch_path = Path(kill_switch_path)
        self.max_market_stale_ms = int(max_market_stale_ms)
        self.max_user_stream_stale_ms = int(max_user_stream_stale_ms)
        self.max_open_orders = int(max_open_orders)
        self.state = ExecutionState()
        self.rules: SymbolRules | None = None
        self._lock = threading.RLock()

    def load_rules(self) -> SymbolRules:
        rules = self.rest.exchange_info(self.symbol)
        if rules.status != "TRADING":
            raise ProductionSafetyError(f"{self.symbol} status={rules.status}")
        self.rules = rules
        return rules

    def trip(self, reason: str) -> None:
        with self._lock:
            self.state.authorized = False
            self.state.kill_switch = True
            self.state.kill_reason = reason
            self.state.reconciliation_ok = False
        try:
            self.rest.cancel_all(self.symbol)
        except Exception:
            pass

    def update_market_heartbeat(self, event_ms: int, synchronized: bool) -> None:
        with self._lock:
            self.state.last_market_event_ms = int(event_ms)
            self.state.book_synchronized = bool(synchronized)

    def update_trade_heartbeat(self, event_ms: int) -> None:
        with self._lock:
            self.state.last_trade_event_ms = int(event_ms)
            self.state.trade_stream_healthy = True

    def update_user_heartbeat(self, event_ms: int) -> None:
        with self._lock:
            self.state.last_user_event_ms = int(event_ms)
            self.state.user_stream_healthy = True

    def update_user_stream_health(
        self, healthy: bool, event_ms: int | None = None, reason: str = ""
    ) -> None:
        now_ms = int(time.time() * 1000) if event_ms is None else int(event_ms)
        with self._lock:
            self.state.last_user_event_ms = now_ms
            self.state.user_stream_healthy = bool(healthy)
        if not healthy and reason:
            self.trip(reason)

    def update_position(self, position_qty: float, mark_price: float) -> None:
        notional = abs(float(position_qty) * float(mark_price))
        with self._lock:
            self.state.position_qty = float(position_qty)
            self.state.position_notional_usd = notional
        if not math.isfinite(notional) or notional > self.max_position_notional_usd + 1e-6:
            self.trip(f"position limit exceeded: {notional:.4f} USD")

    def update_order_event(self, event: dict[str, Any]) -> None:
        event_ms = int(event.get("E", event.get("T", time.time() * 1000)))
        self.update_user_heartbeat(event_ms)
        order = event.get("o", {})
        cid = str(order.get("c", ""))
        if not cid.startswith("AFH01-"):
            return
        status = str(order.get("X", ""))
        with self._lock:
            if status in {"FILLED", "CANCELED", "EXPIRED", "REJECTED", "EXPIRED_IN_MATCH"}:
                self.state.open_orders.pop(cid, None)
            else:
                self.state.open_orders[cid] = order

    def update_account_event(self, event: dict[str, Any]) -> None:
        event_ms = int(event.get("E", event.get("T", time.time() * 1000)))
        self.update_user_heartbeat(event_ms)
        for p in event.get("a", {}).get("P", []):
            if p.get("s") != self.symbol:
                continue
            self.update_position(float(p.get("pa", 0.0)), float(p.get("mp", 0.0)))

    def reconcile(self) -> None:
        try:
            positions = self.rest.position_risk(self.symbol)
            orders = self.rest.open_orders(self.symbol)
        except Exception as exc:
            self.trip(f"REST reconciliation failure: {exc}")
            return

        managed: dict[str, dict[str, Any]] = {}
        unmanaged: list[str] = []
        for order in orders:
            cid = str(order.get("clientOrderId", ""))
            if cid.startswith("AFH01-"):
                managed[cid] = order
            else:
                unmanaged.append(cid)

        if unmanaged:
            self.trip(f"unmanaged open order detected: {unmanaged}")
            return

        qty = 0.0
        mark = 0.0
        for row in positions:
            if row.get("symbol") == self.symbol:
                qty = float(row.get("positionAmt", 0.0))
                mark = float(row.get("markPrice", 0.0))
                break

        self.update_position(qty, mark)
        with self._lock:
            self.state.open_orders = managed
            self.state.reconciliation_ok = not self.state.kill_switch

        if len(managed) > self.max_open_orders:
            self.trip("managed open-order limit exceeded")

    def health_check(self, now_ms: int | None = None) -> None:
        now = int(time.time() * 1000) if now_ms is None else int(now_ms)
        if self.kill_switch_path.exists():
            self.trip("external kill switch detected")
            return
        with self._lock:
            market_age = (
                now - self.state.last_market_event_ms
                if self.state.last_market_event_ms else 10**9
            )
            user_age = (
                now - self.state.last_user_event_ms
                if self.state.last_user_event_ms else 10**9
            )
            trade_age = (
                now - self.state.last_trade_event_ms
                if self.state.last_trade_event_ms else 10**9
            )
            blocked = self.state.kill_switch
            book_ok = self.state.book_synchronized
            user_ok = self.state.user_stream_healthy
            trade_ok = self.state.trade_stream_healthy
            recon_ok = self.state.reconciliation_ok

        if blocked:
            return
        if not book_ok:
            self.trip("book not synchronized")
        elif market_age > self.max_market_stale_ms:
            self.trip(f"market data stale: {market_age}ms")
        elif not user_ok or user_age > self.max_user_stream_stale_ms:
            self.trip(f"user stream stale: {user_age}ms")
        elif not trade_ok or trade_age > self.max_market_stale_ms:
            self.trip(f"trade stream stale: {trade_age}ms")
        elif not recon_ok:
            self.trip("reconciliation not confirmed")

    def authorize(self) -> None:
        manifest = DeploymentManifest.load(self.manifest_path)
        if not manifest.authorized:
            raise ProductionSafetyError("deployment manifest not authorized")
        if manifest.candidate_config_sha256 != self.candidate_config_sha256:
            raise ProductionSafetyError("candidate config SHA mismatch")
        if manifest.required_research_commit != self.research_reference_commit:
            raise ProductionSafetyError("research reference mismatch")
        if manifest.forward_certification_status != "PASS":
            raise ProductionSafetyError("forward certification != PASS")
        if manifest.production_identity_status != "PASS":
            raise ProductionSafetyError("production identity != PASS")
        if manifest.execution_authorization != "AUTHORIZED":
            raise ProductionSafetyError("execution authorization != AUTHORIZED")
        if self.kill_switch_path.exists():
            raise ProductionSafetyError("external kill switch present")

        self.rest.sync_clock()
        self.load_rules()
        self.reconcile()
        self.health_check()

        if self.state.kill_switch:
            raise ProductionSafetyError(f"kill switch: {self.state.kill_reason}")
        if not self.state.book_synchronized:
            raise ProductionSafetyError("book synchronization gate not satisfied")
        if not self.state.user_stream_healthy:
            raise ProductionSafetyError("user-data stream gate not satisfied")
        if not self.state.trade_stream_healthy:
            raise ProductionSafetyError("trade stream gate not satisfied")
        if not self.state.reconciliation_ok:
            raise ProductionSafetyError("reconciliation gate not satisfied")

        with self._lock:
            self.state.authorized = True

    def cancel_managed_orders(self) -> None:
        with self._lock:
            client_ids = list(self.state.open_orders)
        for client_id in client_ids:
            try:
                self.rest.cancel_order(self.symbol, client_id)
            except Exception as exc:
                self.trip(f"managed order cancellation failed: {exc}")
                raise ProductionSafetyError(str(exc)) from exc
        self.reconcile()
        if self.state.kill_switch:
            raise ProductionSafetyError(self.state.kill_reason)

    def validate_quote(
        self,
        *,
        side: str,
        price: float,
        qty: float,
        best_bid: float,
        best_ask: float,
    ) -> tuple[Decimal, Decimal]:
        self.health_check()
        with self._lock:
            rules = self.rules
            kill = self.state.kill_switch
            position = self.state.position_qty
            open_count = len(self.state.open_orders)

        with self._lock:
            authorized = self.state.authorized
        if not authorized:
            raise ProductionSafetyError("execution authorization gate not satisfied")
        if kill:
            raise ProductionSafetyError(self.state.kill_reason)
        if rules is None:
            raise ProductionSafetyError("exchange rules not loaded")
        if open_count >= self.max_open_orders:
            raise ProductionSafetyError("open-order limit reached")

        if side == "BUY":
            p = rules.floor_price(price)
            if p >= Decimal(str(best_ask)):
                raise ProductionSafetyError("BUY would cross ask")
        elif side == "SELL":
            p = rules.ceil_price(price)
            if p <= Decimal(str(best_bid)):
                raise ProductionSafetyError("SELL would cross bid")
        else:
            raise ProductionSafetyError("invalid side")

        q = rules.floor_qty(qty)
        rules.validate_price(p)
        rules.validate_qty(q, p)

        projected = position + float(q) if side == "BUY" else position - float(q)
        projected_notional = abs(projected * float(p))
        if projected_notional > self.max_position_notional_usd + 1e-6:
            raise ProductionSafetyError(
                f"projected position exceeds limit: {projected_notional:.4f} USD"
            )
        return p, q

    def submit_quote(
        self,
        *,
        side: str,
        price: float,
        qty: float,
        best_bid: float,
        best_ask: float,
        client_order_id: str,
    ) -> dict[str, Any]:
        if not client_order_id.startswith("AFH01-"):
            raise ProductionSafetyError("managed clientOrderId required")

        p, q = self.validate_quote(
            side=side,
            price=price,
            qty=qty,
            best_bid=best_bid,
            best_ask=best_ask,
        )
        try:
            result = self.rest.new_post_only_limit(
                self.symbol, side, q, p, client_order_id
            )
        except AmbiguousOrderError:
            self.trip("ambiguous order response; reconcile before retry")
            raise
        except Exception as exc:
            self.trip(f"order submission failed: {exc}")
            raise

        with self._lock:
            self.state.open_orders[client_order_id] = result
        return result


class UserDataStreamMonitor:
    """Authenticated USDⓈ-M listenKey monitor with explicit connection health."""

    def __init__(
        self,
        rest: BinanceFuturesREST,
        on_event: Callable[[dict[str, Any]], None],
        ws_url_template: str = "wss://fstream.binance.com/private/ws/{listen_key}",
        on_status: Callable[[bool, int, str], None] | None = None,
    ) -> None:
        self.rest = rest
        self.on_event = on_event
        self.ws_url_template = ws_url_template
        self.on_status = on_status
        self.listen_key: str | None = None
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.keepalive_thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.listen_key = self.rest.create_listen_key()
        self.thread = threading.Thread(target=self._run, name="AFH-user-stream", daemon=True)
        self.thread.start()
        self.keepalive_thread = threading.Thread(
            target=self._keepalive, name="AFH-user-stream-keepalive", daemon=True
        )
        self.keepalive_thread.start()

    def _keepalive(self) -> None:
        while not self.stop_event.wait(30 * 60):
            try:
                if self.listen_key:
                    self.listen_key = self.rest.keepalive_listen_key(self.listen_key)
            except Exception as exc:
                if self.on_status:
                    self.on_status(
                        False,
                        int(time.time() * 1000),
                        f"user stream keepalive failed: {exc}",
                    )
                return

    def _run(self) -> None:
        if not self.listen_key:
            return
        url = self.ws_url_template.format(listen_key=self.listen_key)

        def on_message(_ws: websocket.WebSocketApp, raw: str) -> None:
            try:
                event = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                return
            self.on_event(event)

        def on_open(_ws: websocket.WebSocketApp) -> None:
            if self.on_status:
                self.on_status(
                    True, int(time.time() * 1000), "user stream connected"
                )

        def on_pong(_ws: websocket.WebSocketApp, _payload: bytes) -> None:
            if self.on_status:
                self.on_status(
                    True, int(time.time() * 1000), "user stream pong"
                )

        def on_error(_ws: websocket.WebSocketApp, error: Any) -> None:
            if self.on_status:
                self.on_status(
                    False,
                    int(time.time() * 1000),
                    f"user stream error: {error}",
                )

        def on_close(
            _ws: websocket.WebSocketApp, _code: Any, _msg: Any
        ) -> None:
            if self.on_status and not self.stop_event.is_set():
                self.on_status(
                    False, int(time.time() * 1000), "user stream closed"
                )

        app = websocket.WebSocketApp(
            url,
            on_message=on_message,
            on_open=on_open,
            on_pong=on_pong,
            on_error=on_error,
            on_close=on_close,
        )
        app.run_forever(ping_interval=20, ping_timeout=10)

    def stop(self) -> None:
        self.stop_event.set()
