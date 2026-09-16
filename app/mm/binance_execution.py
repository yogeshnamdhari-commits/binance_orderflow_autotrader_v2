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
    """Signed USD-M Futures REST order adapter.

    This adapter never bypasses the V20 ExecutionGateway. It only performs an
    exchange request after the gateway has passed risk/reconciliation gates.
    """

    def __init__(self, config: BinanceExecutionConfig, session: requests.Session | None = None):
        self.config = config
        self.session = session or requests.Session()
        self.session.headers.update({"X-MBX-APIKEY": config.api_key})

    def _signed_request(self, method: str, path: str, params: dict) -> requests.Response:
        params = dict(params)
        params.setdefault("timestamp", int(time.time() * 1000))
        params.setdefault("recvWindow", self.config.recv_window_ms)
        query = urlencode(params)
        signature = hmac.new(
            self.config.api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        params["signature"] = signature
        url = f"{self.config.base_url}{path}"
        response = self.session.request(
            method,
            url,
            params=params,
            timeout=self.config.timeout_s,
        )
        response.raise_for_status()
        return response

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
        response = self._signed_request("POST", "/fapi/v1/order", self._order_payload(submission))
        data = response.json()
        status = str(data.get("status", "UNKNOWN"))
        return ExecutionResult(
            status=status,
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
