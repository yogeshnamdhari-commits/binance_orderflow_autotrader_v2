"""Forward execution evidence gate for Binance USD-M demo/test infrastructure.

This script never targets the production trading endpoint. It performs one
small post-only lifecycle, attempts a safe price modification, checks duplicate
client-order-id rejection, listens for user-data events, reconnects once, and
reconciles final order/position state. A passive fill is recorded only when an
actual ORDER_TRADE_UPDATE execution event or executedQty>0 is observed.

Full forward-validation status remains NOT_PROVEN unless an actual execution
is observed. A clean submit/query/modify/cancel lifecycle alone is not treated
as proof of passive-fill behavior.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import threading
import time
import uuid
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from urllib.parse import urlencode, urlparse

import requests

from app.mm.binance_user_stream import BinanceUSDMUserStream

BASE = os.getenv("BINANCE_ORDER_BASE_URL", "https://demo-fapi.binance.com").rstrip("/")
KEY = os.getenv("BINANCE_API_KEY", "")
SECRET = os.getenv("BINANCE_API_SECRET", "")
SYMBOL = os.getenv("V20_SYMBOL", "BTCUSDT")
HOLD_SECONDS = int(os.getenv("V20_FORWARD_HOLD_SECONDS", "90"))

ALLOWED_HOSTS = {"demo-fapi.binance.com", "testnet.binancefuture.com"}


def dec(value: object) -> Decimal:
    return Decimal(str(value or "0"))


def signed_request(method: str, path: str, params: dict[str, object] | None = None) -> requests.Response:
    p = {str(k): str(v) for k, v in dict(params or {}).items()}
    p.setdefault("timestamp", str(int(time.time() * 1000)))
    p.setdefault("recvWindow", "5000")
    query = urlencode(p)
    p["signature"] = hmac.new(SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    return requests.request(
        method,
        BASE + path,
        params=p,
        headers={"X-MBX-APIKEY": KEY},
        timeout=15,
    )


def normalize(value: Decimal, step: Decimal, rounding) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=rounding) * step


def main() -> int:
    parsed = urlparse(BASE)
    if parsed.scheme != "https" or parsed.netloc not in ALLOWED_HOSTS:
        raise SystemExit("FORWARD_GATE_BLOCKED: only Binance demo/testnet endpoints are permitted")
    if not KEY or not SECRET:
        raise SystemExit("FORWARD_GATE_BLOCKED: Binance demo/test credentials are required")

    exchange = requests.get(BASE + "/fapi/v1/exchangeInfo", timeout=15)
    exchange.raise_for_status()
    info = next((s for s in exchange.json().get("symbols", []) if s.get("symbol") == SYMBOL), None)
    if not info or info.get("status") != "TRADING":
        raise SystemExit(f"FORWARD_GATE_BLOCKED: {SYMBOL} is not tradable")
    filters = {f["filterType"]: f for f in info.get("filters", [])}
    tick = dec(filters["PRICE_FILTER"]["tickSize"])
    step = dec(filters["LOT_SIZE"]["stepSize"])
    min_qty = dec(filters["LOT_SIZE"]["minQty"])
    max_qty = dec(filters["LOT_SIZE"]["maxQty"])
    min_notional = dec((filters.get("MIN_NOTIONAL") or {}).get("notional", "0"))

    account_resp = signed_request("GET", "/fapi/v2/account")
    account_resp.raise_for_status()

    initial_positions_resp = signed_request("GET", "/fapi/v2/positionRisk", {"symbol": SYMBOL})
    initial_positions_resp.raise_for_status()
    initial_positions = initial_positions_resp.json()

    events: list[dict] = []
    statuses: list[dict] = []

    def event_cb(event) -> None:
        payload = getattr(event, "raw", event)
        events.append({"event": str(getattr(event, "event_type", type(event).__name__)), "raw": str(payload)})

    def status_cb(status) -> None:
        statuses.append(dict(status) if isinstance(status, dict) else {"status": str(status)})

    stream = BinanceUSDMUserStream(api_key=KEY, event_cb=event_cb, status_cb=status_cb)
    thread = threading.Thread(target=stream.run, daemon=True)
    thread.start()
    time.sleep(3)

    ticker = requests.get(BASE + "/fapi/v1/ticker/bookTicker", params={"symbol": SYMBOL}, timeout=15)
    ticker.raise_for_status()
    best_bid = dec(ticker.json()["bidPrice"])
    price = normalize(best_bid - tick, tick, ROUND_DOWN)
    qty = normalize(min_qty if min_qty > 0 else step, step, ROUND_UP)
    if min_notional > 0 and price * qty < min_notional:
        qty = normalize(min_notional / price, step, ROUND_UP)
    if max_qty > 0 and qty > max_qty:
        raise SystemExit("FORWARD_GATE_BLOCKED: no valid minimum quantity")

    client_id = "V20FG-" + uuid.uuid4().hex[:20]
    order = {
        "symbol": SYMBOL,
        "side": "BUY",
        "type": "LIMIT",
        "timeInForce": "GTX",
        "quantity": format(qty, "f"),
        "price": format(price, "f"),
        "newClientOrderId": client_id,
        "selfTradePreventionMode": "EXPIRE_MAKER",
    }

    submit = signed_request("POST", "/fapi/v1/order", order)
    submit.raise_for_status()
    submitted = submit.json()
    order_id = submitted["orderId"]

    queried = signed_request("GET", "/fapi/v1/order", {"symbol": SYMBOL, "orderId": order_id})
    queried.raise_for_status()
    queried_json = queried.json()
    if queried_json.get("clientOrderId") != client_id:
        raise SystemExit("FORWARD_GATE_FAILURE: exchange clientOrderId mismatch")

    # A duplicate client order id must be rejected rather than silently creating a second order.
    duplicate = signed_request("POST", "/fapi/v1/order", order)
    duplicate_rejected = duplicate.status_code >= 400

    # Move the passive quote one tick farther away while preserving a non-crossing order.
    replacement_price = normalize(price - tick, tick, ROUND_DOWN)
    modify = signed_request(
        "PUT",
        "/fapi/v1/order",
        {
            "symbol": SYMBOL,
            "orderId": order_id,
            "side": "BUY",
            "quantity": format(qty, "f"),
            "price": format(replacement_price, "f"),
            "priceMatch": "NONE",
        },
    )
    modify_ok = modify.status_code < 400

    # Allow a genuine market interaction to produce a partial/full fill if one occurs.
    deadline = time.monotonic() + max(1, HOLD_SECONDS)
    observed_executed_qty = dec(queried_json.get("executedQty"))
    while time.monotonic() < deadline:
        current = signed_request("GET", "/fapi/v1/order", {"symbol": SYMBOL, "orderId": order_id})
        if current.status_code < 400:
            current_json = current.json()
            observed_executed_qty = max(observed_executed_qty, dec(current_json.get("executedQty")))
            if observed_executed_qty > 0 or current_json.get("status") in {"FILLED", "CANCELED", "EXPIRED", "EXPIRED_IN_MATCH"}:
                break
        time.sleep(3)

    cancel = signed_request("DELETE", "/fapi/v1/order", {"symbol": SYMBOL, "orderId": order_id})
    cancel_ok = cancel.status_code < 400

    final_order = signed_request("GET", "/fapi/v1/order", {"symbol": SYMBOL, "orderId": order_id})
    final_order.raise_for_status()
    final_json = final_order.json()
    observed_executed_qty = max(observed_executed_qty, dec(final_json.get("executedQty")))

    final_positions_resp = signed_request("GET", "/fapi/v2/positionRisk", {"symbol": SYMBOL})
    final_positions_resp.raise_for_status()
    final_positions = final_positions_resp.json()

    # Reconnect user stream once and verify the transport can be recreated.
    stream.stop()
    thread.join(timeout=5)
    reconnect_status: list[dict] = []
    stream2 = BinanceUSDMUserStream(api_key=KEY, status_cb=lambda s: reconnect_status.append(s if isinstance(s, dict) else {"status": str(s)}))
    thread2 = threading.Thread(target=stream2.run, daemon=True)
    thread2.start()
    time.sleep(3)
    stream2.stop()
    thread2.join(timeout=5)

    user_stream_connected = any(s.get("status") == "USER_STREAM_CONNECTED" for s in statuses + reconnect_status)
    user_stream_reconnected = any(s.get("status") == "USER_STREAM_CONNECTED" for s in reconnect_status)

    report = {
        "symbol": SYMBOL,
        "endpoint": BASE,
        "live_order_submission": False,
        "lifecycle": {
            "submit_ack": True,
            "query_ack": True,
            "duplicate_client_order_id_rejected": duplicate_rejected,
            "modify_ack": modify_ok,
            "cancel_ack": cancel_ok,
            "final_order_status": final_json.get("status"),
            "executed_qty": float(observed_executed_qty),
            "actual_fill_observed": observed_executed_qty > 0,
            "user_stream_connected": user_stream_connected,
            "user_stream_reconnected": user_stream_reconnected,
        },
        "initial_positions": initial_positions,
        "final_positions": final_positions,
        "full_forward_validation_pass": all([
            duplicate_rejected,
            modify_ok,
            cancel_ok,
            user_stream_connected,
            user_stream_reconnected,
            observed_executed_qty > 0,
        ]),
    }
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0 if report["full_forward_validation_pass"] else 2


if __name__ == "__main__":
    sys.exit(main())
