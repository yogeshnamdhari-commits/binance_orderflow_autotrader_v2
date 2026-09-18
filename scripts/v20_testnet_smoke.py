from __future__ import annotations

import hashlib
import hmac
import os
import sys
import time
from decimal import Decimal, ROUND_UP
from urllib.parse import urlencode, urlparse

import requests


BASE = os.getenv("BINANCE_ORDER_BASE_URL", "https://demo-fapi.binance.com").rstrip("/")
KEY = os.getenv("BINANCE_API_KEY", "")
SECRET = os.getenv("BINANCE_API_SECRET", "")
SYMBOL = os.getenv("V20_SYMBOL", "BTCUSDT")
EXECUTE = os.getenv("V20_TESTNET_EXECUTE", "0") == "1"

# Only Binance Futures demo/test infrastructure is accepted here. Production
# endpoints and arbitrary URLs are rejected before any signed request is sent.
ALLOWED_DEMO_HOSTS = {"demo-fapi.binance.com", "testnet.binancefuture.com"}


def require_env() -> None:
    missing = [name for name, value in {
        "BINANCE_API_KEY": KEY,
        "BINANCE_API_SECRET": SECRET,
    }.items() if not value]
    if missing:
        raise SystemExit("missing environment: " + ", ".join(missing))
    parsed = urlparse(BASE)
    if parsed.scheme != "https" or parsed.netloc not in ALLOWED_DEMO_HOSTS:
        raise SystemExit(
            "refusing to run testnet smoke: BINANCE_ORDER_BASE_URL must be an approved Binance Futures demo endpoint"
        )


def signed_request(method: str, path: str, params: dict | None = None) -> requests.Response:
    params = dict(params or {})
    params.setdefault("timestamp", int(time.time() * 1000))
    params.setdefault("recvWindow", 5000)
    query = urlencode(params)
    sig = hmac.new(SECRET.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
    params["signature"] = sig
    response = requests.request(
        method,
        BASE + path,
        params=params,
        headers={"X-MBX-APIKEY": KEY},
        timeout=10,
    )
    response.raise_for_status()
    return response


def d(value: object) -> Decimal:
    return Decimal(str(value or "0"))


def round_up(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_UP) * step


def valid_passive_order(info: dict, bid_price: Decimal) -> tuple[Decimal, Decimal]:
    filters = {f["filterType"]: f for f in info.get("filters", [])}
    price_filter = filters["PRICE_FILTER"]
    lot_filter = filters["LOT_SIZE"]
    tick = d(price_filter["tickSize"])
    min_price = d(price_filter["minPrice"])
    step = d(lot_filter["stepSize"])
    min_qty = d(lot_filter["minQty"])
    max_qty = d(lot_filter["maxQty"])
    min_notional_filter = filters.get("MIN_NOTIONAL", {})
    min_notional = d(min_notional_filter.get("notional", min_notional_filter.get("minNotional")))

    price = bid_price - tick
    if tick > 0:
        price = (price / tick).to_integral_value(rounding=ROUND_UP) * tick
    if min_price > 0:
        price = max(price, min_price)
    qty = min_qty if min_qty > 0 else step
    if step > 0:
        qty = round_up(qty, step)
    if min_notional > 0 and price * qty < min_notional:
        qty = round_up(min_notional / price, step)
    if max_qty > 0 and qty > max_qty:
        raise SystemExit("no valid BTCUSDT smoke quantity satisfies current exchange filters")
    return price, qty


def main() -> int:
    require_env()
    exchange = requests.get(BASE + "/fapi/v1/exchangeInfo", timeout=10)
    exchange.raise_for_status()
    symbols = {row["symbol"]: row for row in exchange.json().get("symbols", [])}
    info = symbols.get(SYMBOL)
    if not info or info.get("status") != "TRADING":
        raise SystemExit(f"symbol not tradable on configured demo endpoint: {SYMBOL}")

    account = signed_request("GET", "/fapi/v2/account").json()
    print("ACCOUNT_OK", account.get("canTrade"), account.get("totalWalletBalance"))
    print("SYMBOL_OK", SYMBOL)

    if not EXECUTE:
        print("EXECUTION_TEST_SKIPPED: set V20_TESTNET_EXECUTE=1 for one explicit post-only order lifecycle")
        return 0

    best = requests.get(BASE + "/fapi/v1/ticker/bookTicker", params={"symbol": SYMBOL}, timeout=10).json()
    bid = d(best["bidPrice"])
    price, qty = valid_passive_order(info, bid)
    order = {
        "symbol": SYMBOL,
        "side": "BUY",
        "type": "LIMIT",
        "timeInForce": "GTX",
        "quantity": format(qty, "f").rstrip("0").rstrip("."),
        "price": format(price, "f").rstrip("0").rstrip("."),
        "newClientOrderId": "V20SMOKE-" + str(int(time.time() * 1000)),
    }
    result = signed_request("POST", "/fapi/v1/order", order).json()
    order_id = result.get("orderId")
    print("ORDER_SUBMIT_OK", order_id, result.get("status"), result.get("clientOrderId"))

    current = signed_request("GET", "/fapi/v1/order", {"symbol": SYMBOL, "orderId": order_id}).json()
    print("ORDER_QUERY_OK", current.get("status"), current.get("executedQty"))

    cancelled = signed_request("DELETE", "/fapi/v1/order", {"symbol": SYMBOL, "orderId": order_id}).json()
    print("ORDER_CANCEL_OK", cancelled.get("status"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
