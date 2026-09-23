from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from app.mm.binance_user_stream import BinanceUSDMUserStream
from scripts.v20_testnet_smoke import ALLOWED_DEMO_HOSTS

BASE = os.getenv("BINANCE_ORDER_BASE_URL", "https://demo-fapi.binance.com").rstrip("/")
API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")
SYMBOL = os.getenv("V20_SYMBOL", "BTCUSDT")
EXECUTE = os.getenv("V20_TESTNET_EXECUTE", "0") == "1"
WAIT_SECONDS = float(os.getenv("V20_USER_STREAM_WAIT_SECONDS", "8"))
EVIDENCE_PATH = Path(os.getenv("V20_EVIDENCE_PATH", "artifacts/v20_testnet_gate.json"))


def fail(message: str) -> None:
    raise SystemExit(message)


def validate_environment() -> None:
    if not API_KEY or not API_SECRET:
        fail("BINANCE_API_KEY and BINANCE_API_SECRET are required")
    parsed = urlparse(BASE)
    if parsed.scheme != "https" or parsed.netloc not in ALLOWED_DEMO_HOSTS:
        fail("refusing authenticated gate: REST endpoint is not an approved Binance Futures demo endpoint")


def account() -> dict:
    from scripts.v20_testnet_smoke import signed_request
    return signed_request("GET", "/fapi/v2/account").json()


def open_orders() -> list[dict]:
    from scripts.v20_testnet_smoke import signed_request
    return signed_request("GET", "/fapi/v1/openOrders", {"symbol": SYMBOL}).json()


def position() -> list[dict]:
    from scripts.v20_testnet_smoke import signed_request
    return signed_request("GET", "/fapi/v2/positionRisk", {"symbol": SYMBOL}).json()


def run_user_stream() -> tuple[BinanceUSDMUserStream, threading.Thread]:
    control_url = os.getenv("BINANCE_USER_STREAM_API_URL", "wss://testnet.binancefuture.com/ws-fapi/v1")
    private_url = os.getenv("BINANCE_PRIVATE_STREAM_BASE_URL", "wss://fstream.binancefuture.com/private/ws")
    statuses: list[dict] = []
    stream = BinanceUSDMUserStream(
        api_key=API_KEY,
        control_url=control_url,
        private_stream_base=private_url,
        status_cb=statuses.append,
    )
    stream.status_cb = statuses.append
    thread = threading.Thread(target=stream.run, daemon=True)
    thread.start()
    deadline = time.time() + WAIT_SECONDS
    while time.time() < deadline:
        healthy, _, _ = stream.guard.health(int(time.time() * 1000))
        if healthy:
            return stream, thread
        time.sleep(0.25)
    stream.stop()
    fail(f"authenticated private user stream did not become healthy within {WAIT_SECONDS}s")
    return stream, thread


def shutdown_stream(stream: BinanceUSDMUserStream) -> None:
    try:
        stream.stop()
    except Exception:
        pass


def main() -> int:
    validate_environment()
    evidence: dict = {
        "base_url": BASE,
        "symbol": SYMBOL,
        "execute": EXECUTE,
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    acct = account()
    evidence["account_can_trade"] = bool(acct.get("canTrade"))
    if not evidence["account_can_trade"]:
        fail("demo account reports canTrade=false")

    initial_orders = open_orders()
    initial_position = position()
    evidence["initial_open_orders"] = initial_orders
    evidence["initial_position"] = initial_position

    stream, _ = run_user_stream()
    evidence["private_stream_connected"] = True

    try:
        if EXECUTE:
            # Reuse the hardened one-order smoke path. It submits only to the
            # allowlisted demo endpoint, then queries and cancels immediately.
            from scripts.v20_testnet_smoke import main as smoke_main
            rc = smoke_main()
            if rc != 0:
                fail(f"demo smoke order lifecycle returned {rc}")
            evidence["rest_order_lifecycle"] = "PASS"
        else:
            evidence["rest_order_lifecycle"] = "NOT_RUN"

        remaining = open_orders()
        final_position = position()
        evidence["final_open_orders"] = remaining
        evidence["final_position"] = final_position
        if remaining:
            fail(f"demo gate left open orders: {remaining}")
        evidence["reconciled_open_orders"] = True
        evidence["reconciled_position_snapshot"] = True
    finally:
        shutdown_stream(stream)

    evidence["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
