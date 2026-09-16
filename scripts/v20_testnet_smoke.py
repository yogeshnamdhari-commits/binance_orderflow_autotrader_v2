from __future__ import annotations

import hashlib
import hmac
import os
import sys
import time
from urllib.parse import urlencode

import requests


BASE = os.getenv("BINANCE_ORDER_BASE_URL", "").rstrip("/")
KEY = os.getenv("BINANCE_API_KEY", "")
SECRET = os.getenv("BINANCE_API_SECRET", "")
SYMBOL = os.getenv("V20_SYMBOL", "BTCUSDT")
EXECUTE = os.getenv("V20_TESTNET_EXECUTE", "0") == "1"


def require_env() -> None:
    missing = [name for name, value in {
        "BINANCE_ORDER_BASE_URL": BASE,
        "BINANCE_API_KEY": KEY,
        "BINANCE_API_SECRET": SECRET,
    }.items() if not value]
    if missing:
        raise SystemExit("missing environment: " + ", ".join(missing))
    if BASE in {"https://fapi.binance.com", "https://fapi.binance.com/"}:
        raise SystemExit("refusing to run testnet smoke against Binance production REST")


def signed_get(path: str, params: dict | None = None) -> requests.Response:
    params = dict(params or {})
    params.setdefault("timestamp", int(time.time() * 1000))
    params.setdefault("recvWindow", 5000)
    query = urlencode(params)
    sig = hmac.new(SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    params["signature"] = sig
    response = requests.get(
        BASE + path,
        params=params,
        headers={"X-MBX-APIKEY": KEY},
        timeout=10,
    )
    response.raise_for_status()
    return response


def main() -> int:
    require_env()
    exchange = requests.get(BASE + "/fapi/v1/exchangeInfo", timeout=10)
    exchange.raise_for_status()
    symbols = {row["symbol"]: row for row in exchange.json().get("symbols", [])}
    info = symbols.get(SYMBOL)
    if not info or info.get("status") != "TRADING":
        raise SystemExit(f"symbol not tradable on configured endpoint: {SYMBOL}")

    account = signed_get("/fapi/v2/account").json()
    print("ACCOUNT_OK", account.get("canTrade"), account.get("totalWalletBalance"))
    print("SYMBOL_OK", SYMBOL)

    if not EXECUTE:
        print("EXECUTION_TEST_SKIPPED: set V20_TESTNET_EXECUTE=1 for one explicit post-only order lifecycle")
        return 0

    filters = {f["filterType"]: f for f in info.get("filters", [])}
    tick = float(filters["PRICE_FILTER"]["tickSize"])
    step = float(filters["LOT_SIZE"]["stepSize"])
    min_qty = float(filters["LOT_SIZE"]["minQty"])
    best = requests.get(BASE + "/fapi/v1/ticker/bookTicker", params={"symbol": SYMBOL}, timeout=10).json()
    bid = float(best["bidPrice"])
    price = (bid - tick) if bid > tick else bid
    price = round(round(price / tick) * tick, 12)
    qty = max(min_qty, step)
    qty = round(round(qty / step) * step, 12)
    order = {
        "symbol": SYMBOL,
        "side": "BUY",
        "type": "LIMIT",
        "timeInForce": "GTX",
        "quantity": f"{qty:.12f}".rstrip("0").rstrip("."),
        "price": f"{price:.12f}".rstrip("0").rstrip("."),
        "newClientOrderId": "V20SMOKE-" + str(int(time.time() * 1000)),
    }
    # Reuse the adapter semantics: signed POST is generated here so this file
    # remains standalone and does not import live trading runtime code.
    params = dict(order)
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 5000
    query = urlencode(params)
    params["signature"] = hmac.new(SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    response = requests.post(BASE + "/fapi/v1/order", params=params,
                             headers={"X-MBX-APIKEY": KEY}, timeout=10)
    response.raise_for_status()
    data = response.json()
    order_id = data.get("orderId")
    print("ORDER_SUBMIT_OK", order_id, data.get("status"), data.get("clientOrderId"))

    cancel = signed_get("/fapi/v1/order", {"symbol": SYMBOL, "orderId": order_id})
    current = cancel.json()
    print("ORDER_QUERY_OK", current.get("status"), current.get("executedQty"))

    params = {"symbol": SYMBOL, "orderId": order_id, "timestamp": int(time.time() * 1000), "recvWindow": 5000}
    query = urlencode(params)
    params["signature"] = hmac.new(SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    cancelled = requests.delete(BASE + "/fapi/v1/order", params=params,
                                headers={"X-MBX-APIKEY": KEY}, timeout=10)
    cancelled.raise_for_status()
    print("ORDER_CANCEL_OK", cancelled.json().get("status"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
