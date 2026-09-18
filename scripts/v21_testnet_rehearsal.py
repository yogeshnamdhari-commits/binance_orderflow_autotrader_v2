"""Authenticated Binance USD-M testnet lifecycle rehearsal for V21.

The rehearsal is opt-in. It refuses to submit any testnet order unless
BINANCE_TESTNET_ORDER_ENABLE=1 is set. It requires a clean symbol state before
submission, places one post-only order away from the touch, verifies the
authenticated private stream, cancels the order through REST, and verifies
that REST state is flat afterward.

No mainnet endpoint is selected by this script.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from pathlib import Path

import requests

from app.mm.binance_execution import BinanceExecutionConfig, BinanceUSDMExecutionAdapter
from app.mm.binance_user_stream import BinanceUSDMUserStream
from app.mm.user_stream import OrderUpdate, PositionUpdate


def _wait_until(predicate, timeout_s: float, interval_s: float = 0.1) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval_s)
    return False


def run(symbol: str) -> dict:
    enabled = os.getenv("BINANCE_TESTNET_ORDER_ENABLE", "").strip() == "1"
    if not enabled:
        return {
            "status": "NOT_RUN",
            "reason": "BINANCE_TESTNET_ORDER_ENABLE=1 is required to place the opt-in testnet order",
            "private_stream_connected": False,
            "reconciled_open_orders": False,
            "reconciled_position_snapshot": False,
            "rest_order_lifecycle": "NOT_RUN",
        }

    base_url = os.getenv("BINANCE_ORDER_BASE_URL", "")
    if "testnet" not in base_url.lower():
        raise RuntimeError("testnet_only_endpoint_required")

    cfg = BinanceExecutionConfig.from_env()
    adapter = BinanceUSDMExecutionAdapter(cfg)

    # Only a clean symbol state is safe for an automated rehearsal.
    initial_orders = adapter.open_orders(symbol)
    initial_positions = adapter.position_risk(symbol)
    nonzero_position = any(
        abs(float(row.get("positionAmt", 0.0) or 0.0)) > 1e-12
        for row in initial_positions
        if str(row.get("symbol", "")).upper() == symbol.upper()
    )
    if initial_orders or nonzero_position:
        return {
            "status": "LOCKED",
            "reason": "testnet symbol is not clean; refusing to alter existing orders/position",
            "private_stream_connected": False,
            "reconciled_open_orders": False,
            "reconciled_position_snapshot": False,
            "rest_order_lifecycle": "NOT_RUN",
            "initial_open_orders": len(initial_orders),
            "initial_nonzero_position": nonzero_position,
        }

    ticker = requests.get(
        f"{cfg.base_url}/fapi/v1/ticker/bookTicker",
        params={"symbol": symbol.upper()},
        timeout=5,
    )
    ticker.raise_for_status()
    book = ticker.json()
    best_bid = float(book["bidPrice"])
    tick = adapter._constraints_for(symbol).tick_size
    min_qty = adapter._constraints_for(symbol).min_qty
    min_notional = adapter._constraints_for(symbol).min_notional

    # Keep the order passive and away from the touch so the rehearsal should
    # not create a fill while still exercising the authenticated order path.
    price = adapter._constraints_for(symbol).normalize_price(max(tick, best_bid - 10.0 * float(tick)))
    required_qty = max(float(min_qty), float(min_notional) / price if min_notional > 0 else float(min_qty))
    qty = adapter._constraints_for(symbol).normalize_qty(required_qty)
    if qty * price < float(min_notional):
        step = float(adapter._constraints_for(symbol).step_size)
        qty = adapter._constraints_for(symbol).normalize_qty(qty + max(step, 1e-12))
    if qty <= 0 or price <= 0 or qty * price < float(min_notional):
        raise RuntimeError("unable_to_construct_valid_testnet_order")

    events: list[object] = []

    def on_event(event):
        events.append(event)

    stream = BinanceUSDMUserStream(event_cb=on_event, status_cb=lambda _x: None)
    thread = threading.Thread(target=stream.run, daemon=True)
    thread.start()

    connected = _wait_until(lambda: stream.guard.connected, 15.0)
    if not connected:
        stream.stop()
        thread.join(timeout=5)
        return {
            "status": "FAIL",
            "reason": "authenticated_private_stream_failed_to_connect",
            "private_stream_connected": False,
            "reconciled_open_orders": False,
            "reconciled_position_snapshot": False,
            "rest_order_lifecycle": "NOT_RUN",
        }

    client_id = f"V21-TEST-{int(time.time() * 1000)}"
    from app.mm.execution_gateway import Submission

    result = adapter.submit(
        Submission(
            symbol.upper(),
            "BUY",
            qty,
            price,
            client_id,
        )
    )

    accepted = result.status.upper() in {"NEW", "PARTIALLY_FILLED", "PENDING_NEW"}
    saw_order_update = _wait_until(
        lambda: any(
            isinstance(event, OrderUpdate)
            and event.client_id == client_id
            for event in events
        ),
        10.0,
    )

    cancelled = False
    if accepted and result.order_id:
        cancel_result = adapter.cancel(str(result.order_id), symbol)
        cancelled = cancel_result.status.upper() in {
            "CANCELED",
            "CANCELLED",
            "EXPIRED",
            "EXPIRED_IN_MATCH",
        } or cancel_result.status.upper() == "CANCELLED_ALL"
        _wait_until(
            lambda: any(
                isinstance(event, OrderUpdate)
                and event.client_id == client_id
                and event.status.upper() in {"CANCELED", "CANCELLED", "EXPIRED", "EXPIRED_IN_MATCH"}
                for event in events
            ),
            10.0,
        )
    else:
        cancel_result = result

    final_orders = adapter.open_orders(symbol)
    final_positions = adapter.position_risk(symbol)
    final_nonzero_position = any(
        abs(float(row.get("positionAmt", 0.0) or 0.0)) > 1e-12
        for row in final_positions
        if str(row.get("symbol", "")).upper() == symbol.upper()
    )

    private_stream_connected = bool(connected)
    stream.stop()
    thread.join(timeout=5)
    reconciled_open_orders = len(final_orders) == 0
    reconciled_position_snapshot = not final_nonzero_position
    rest_lifecycle = "PASS" if accepted and cancelled else "FAIL"
    status = (
        "PASS"
        if private_stream_connected
        and saw_order_update
        and reconciled_open_orders
        and reconciled_position_snapshot
        and rest_lifecycle == "PASS"
        else "FAIL"
    )
    return {
        "status": status,
        "private_stream_connected": private_stream_connected,
        "order_update_observed": saw_order_update,
        "reconciled_open_orders": reconciled_open_orders,
        "reconciled_position_snapshot": reconciled_position_snapshot,
        "rest_order_lifecycle": rest_lifecycle,
        "client_id": client_id,
        "submitted_status": result.status,
        "submitted_order_id": result.order_id,
        "final_open_orders": len(final_orders),
        "final_nonzero_position": final_nonzero_position,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=os.getenv("V21_TESTNET_SYMBOL", "BTCUSDT"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = run(args.symbol.upper())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
