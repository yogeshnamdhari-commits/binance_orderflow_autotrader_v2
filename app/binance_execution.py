"""Authenticated Binance USD-M Futures execution adapter.

This adapter is deliberately fail-closed.  It can be constructed for paper or
Binance testnet use without credentials, while real order submission requires
an explicit runtime enable flag and the repository governance lock to be off.
Secrets are supplied only through environment variables and are never logged.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import requests


@dataclass(frozen=True)
class BinanceOrder:
    order_id: int
    client_order_id: str
    symbol: str
    side: str
    status: str
    orig_qty: str
    executed_qty: str
    avg_price: str


class BinanceExecutionError(RuntimeError):
    pass


class BinanceFuturesExecution:
    """Signed REST execution with explicit fail-closed governance.

    The default is disabled.  Real submission is allowed only when:
      LIVE_TRADING_ENABLED=true
      ORDERFLOW_BASELINE_V5_NO_LIVE_TRADE=false
      BINANCE_API_KEY and BINANCE_API_SECRET are present

    The caller remains responsible for higher-level risk limits and must use
    reconcile_order() after submission/cancellation to recover exchange truth.
    """

    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 api_secret: str | None = None, session=None,
                 live_enabled: bool | None = None, governance_locked: bool | None = None):
        self.base_url = (base_url or os.getenv("BINANCE_REST", "https://fapi.binance.com")).rstrip("/")
        self.api_key = api_key or os.getenv("BINANCE_API_KEY", "")
        self.api_secret = api_secret or os.getenv("BINANCE_API_SECRET", "")
        self.live_enabled = ((os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true")
                             if live_enabled is None else live_enabled)
        self.governance_locked = ((os.getenv("ORDERFLOW_BASELINE_V5_NO_LIVE_TRADE", "true").lower() == "true")
                                  if governance_locked is None else governance_locked)
        self.session = session or requests.Session()

    @property
    def can_submit_live(self) -> bool:
        return bool(self.live_enabled and not self.governance_locked
                    and self.api_key and self.api_secret)

    def _assert_live(self):
        if not self.can_submit_live:
            raise BinanceExecutionError(
                "live submission locked: explicit runtime enable, credentials, "
                "and governance unlock are required"
            )

    def _signed(self, method: str, path: str, params: dict):
        self._assert_live()
        p = dict(params)
        p.setdefault("timestamp", int(time.time() * 1000))
        p.setdefault("recvWindow", 5000)
        query = urlencode(sorted(p.items()))
        signature = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        headers = {"X-MBX-APIKEY": self.api_key}
        url = f"{self.base_url}{path}?{query}&signature={signature}"
        response = self.session.request(method, url, headers=headers, timeout=10)
        if response.status_code >= 400:
            raise BinanceExecutionError(f"Binance HTTP {response.status_code}: {response.text[:300]}")
        return response.json()

    def submit_market(self, symbol: str, side: str, quantity: str,
                      client_order_id: str | None = None) -> BinanceOrder:
        """Submit a market order after all fail-closed gates pass."""
        params = {"symbol": symbol.upper(), "side": side.upper(),
                  "type": "MARKET", "quantity": quantity}
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        data = self._signed("POST", "/fapi/v1/order", params)
        return self._parse_order(data)

    def cancel(self, symbol: str, order_id: int | None = None,
               client_order_id: str | None = None) -> BinanceOrder:
        if not order_id and not client_order_id:
            raise ValueError("order_id or client_order_id is required")
        params = {"symbol": symbol.upper()}
        if order_id:
            params["orderId"] = order_id
        else:
            params["origClientOrderId"] = client_order_id
        data = self._signed("DELETE", "/fapi/v1/order", params)
        return self._parse_order(data)

    def reconcile_order(self, symbol: str, order_id: int | None = None,
                        client_order_id: str | None = None) -> BinanceOrder:
        """Query exchange truth for lifecycle reconciliation."""
        if not order_id and not client_order_id:
            raise ValueError("order_id or client_order_id is required")
        params = {"symbol": symbol.upper()}
        if order_id:
            params["orderId"] = order_id
        else:
            params["origClientOrderId"] = client_order_id
        data = self._signed("GET", "/fapi/v1/order", params)
        return self._parse_order(data)

    @staticmethod
    def _parse_order(data: dict) -> BinanceOrder:
        return BinanceOrder(
            order_id=int(data["orderId"]),
            client_order_id=str(data.get("clientOrderId", "")),
            symbol=str(data["symbol"]), side=str(data["side"]),
            status=str(data["status"]), orig_qty=str(data.get("origQty", "0")),
            executed_qty=str(data.get("executedQty", "0")),
            avg_price=str(data.get("avgPrice", "0")),
        )
