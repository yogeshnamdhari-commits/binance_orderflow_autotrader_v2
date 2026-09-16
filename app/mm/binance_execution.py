from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import requests

from .execution import ExecutionResult
from .execution_gateway import Submission
from .order_constraints import SymbolConstraints, find_symbol


@dataclass(frozen=True)
class BinanceExecutionConfig:
    base_url: str
    api_key: str
    api_secret: str
    recv_window_ms: int = 5000
    timeout_s: float = 5.0

    @classmethod
    def from_env(cls) -> "BinanceExecutionConfig":
        base_url = os.getenv("BINANCE_ORDER_BASE_URL", "").rstrip("/")
        api_key = os.getenv("BINANCE_API_KEY", "")
        api_secret = os.getenv("BINANCE_API_SECRET", "")
        if not base_url or not api_key or not api_secret:
            raise RuntimeError("BINANCE_ORDER_BASE_URL, BINANCE_API_KEY and BINANCE_API_SECRET are required")
        return cls(base_url, api_key, api_secret)


class BinanceUSDMExecutionAdapter:
    """Signed USD-M Futures REST adapter with exchange-filter enforcement.

    The adapter never bypasses ExecutionGateway. Exchange symbol metadata is
    loaded once per adapter instance and orders are validated against current
    PRICE_FILTER/LOT_SIZE/MIN_NOTIONAL constraints before submission.
    """

    def __init__(self, config: BinanceExecutionConfig, session: requests.Session | None = None):
        self.config = config
        self.session = session or requests.Session()
        self.session.headers.update({"X-MBX-APIKEY": config.api_key})
        self._constraints: dict[str, SymbolConstraints] = {}
        self._exchange_info_loaded = False

    def _signed_request(self, method: str, path: str, params: dict) -> requests.Response:
        params = dict(params)
        params.setdefault("timestamp", int(time.time() * 1000))
        params.setdefault("recvWindow", self.config.recv_window_ms)
        query = urlencode(params)
        signature = hmac.new(self.config.api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
        params["signature"] = signature
        response = self.session.request(method, f"{self.config.base_url}{path}", params=params, timeout=self.config.timeout_s)
        response.raise_for_status()
        return response

    def refresh_exchange_info(self) -> None:
        response = self.session.get(f"{self.config.base_url}/fapi/v1/exchangeInfo", timeout=self.config.timeout_s)
        response.raise_for_status()
        payload = response.json()
        self._constraints = {
            str(info["symbol"]).upper(): SymbolConstraints.from_exchange_info(info)
            for info in payload.get("symbols", [])
            if str(info.get("status", "TRADING")) == "TRADING"
        }
        self._exchange_info_loaded = True

    def _constraints_for(self, symbol: str) -> SymbolConstraints:
        key = symbol.upper()
        if not self._exchange_info_loaded:
            self.refresh_exchange_info()
        constraint = self._constraints.get(key)
        if constraint is None:
            raise RuntimeError(f"exchange_symbol_not_available:{key}")
        return constraint

    @staticmethod
    def _order_payload(submission: Submission) -> dict:
        return {
            "symbol": submission.symbol,
            "side": submission.side,
            "type": "LIMIT",
            "timeInForce": "GTX",
            "quantity": format(submission.qty, ".12f").rstrip("0").rstrip("."),
            "price": format(submission.price, ".12f").rstrip("0").rstrip("."),
            "newClientOrderId": submission.client_id,
        }

    def submit(self, submission: Submission) -> ExecutionResult:
        constraints = self._constraints_for(submission.symbol)
        valid, reasons = constraints.validate(submission.price, submission.qty)
        if not valid:
            return ExecutionResult("REJECTED_LOCAL_FILTER", None, ";".join(reasons), submission.client_id)
        response = self._signed_request("POST", "/fapi/v1/order", self._order_payload(submission))
        data = response.json()
        return ExecutionResult(
            status=str(data.get("status", "UNKNOWN")),
            order_id=str(data.get("orderId")) if data.get("orderId") is not None else None,
            message="binance order submitted",
            client_id=str(data.get("clientOrderId", submission.client_id)),
        )

    def cancel(self, order_id: str) -> ExecutionResult:
        response = self._signed_request("DELETE", "/fapi/v1/order", {"orderId": order_id})
        data = response.json()
        return ExecutionResult(
            status=str(data.get("status", "CANCELLED")),
            order_id=str(data.get("orderId", order_id)),
            message="binance order cancelled",
            client_id=str(data.get("clientOrderId")) if data.get("clientOrderId") else None,
        )
