from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
from decimal import Decimal
from urllib.parse import urlencode, urlparse

import requests


BASE = os.getenv("BINANCE_LIVE_BASE_URL", "https://fapi.binance.com").rstrip("/")
KEY = os.getenv("BINANCE_LIVE_API_KEY", "")
SECRET = os.getenv("BINANCE_LIVE_API_SECRET", "")
SYMBOL = os.getenv("V20_SYMBOL", "BTCUSDT")
CONFIG = os.getenv("V20_CONFIG", "app/mm/config.json")


def signed_get(path: str, params: dict[str, str] | None = None) -> dict:
    params = dict(params or {})
    params.setdefault("timestamp", str(int(time.time() * 1000)))
    params.setdefault("recvWindow", "5000")
    query = urlencode(params)
    signature = hmac.new(SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    params["signature"] = signature
    response = requests.get(
        BASE + path,
        params=params,
        headers={"X-MBX-APIKEY": KEY},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def fail(message: str) -> None:
    raise SystemExit(f"FEE_REALISM_FAILURE: {message}")


def main() -> int:
    parsed = urlparse(BASE)
    if parsed.scheme != "https" or parsed.netloc != "fapi.binance.com":
        fail("BINANCE_LIVE_BASE_URL must be https://fapi.binance.com")
    if not KEY or not SECRET:
        fail("BINANCE_LIVE_API_KEY/BINANCE_LIVE_API_SECRET are required; no fee claim is made without authenticated account data")

    commission = signed_get("/fapi/v1/commissionRate", {"symbol": SYMBOL})
    maker_pct = Decimal(str(commission["makerCommissionRate"])) * Decimal("100")
    taker_pct = Decimal(str(commission["takerCommissionRate"])) * Decimal("100")
    maker_bps = maker_pct * Decimal("100")
    taker_bps = taker_pct * Decimal("100")

    with open(CONFIG, encoding="utf-8") as handle:
        config = json.load(handle)
    configured_maker_bps = Decimal(str(config["maker_fee_bps"]))
    configured_taker_bps = Decimal(str(config["taker_fee_bps"]))

    report = {
        "symbol": SYMBOL,
        "endpoint": BASE,
        "source": "authenticated Binance USDⓈ-M /fapi/v1/commissionRate",
        "maker_fee_bps": float(maker_bps),
        "taker_fee_bps": float(taker_bps),
        "configured_maker_fee_bps": float(configured_maker_bps),
        "configured_taker_fee_bps": float(configured_taker_bps),
        "maker_config_matches": configured_maker_bps == maker_bps,
        "taker_config_matches": configured_taker_bps == taker_bps,
        "orders_submitted": False,
        "passed": configured_maker_bps == maker_bps and configured_taker_bps == taker_bps,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["passed"]:
        fail("stored config fees do not exactly match the authenticated account rates")
    print("LIVE_FEE_REALISM_PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
