#!/usr/bin/env python3
"""Validate one authentic BTCUSDT USDⓈ-M perpetual capture against frozen AFH01.

This is a research gate, not a deployment switch. It refuses spot/non-perpetual
captures and refuses any candidate config other than the frozen AFH01 config.
It reports economics but does not invent or bypass an economic certification rule.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.mm.config import V20Config
from app.mm.event_backtest import run_event_backtest
from scripts.v20_event_backtest_capture import (
    load_events,
    load_perpetual_auxiliary_events,
    load_snapshot,
)


FROZEN_CONFIG = Path("app/mm/config_v21_active_flow_hedge_01bps.json")
FROZEN_CONFIG_SHA256 = "17f9350f139c7f646f5215bf7a0dc41bcb0d79c338f2d76cc29fa33a071a97aa"
RESEARCH_REFERENCE = "a06e8f590634777bbd5ade86ef3b2563194ca2ed"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-dir", required=True, type=Path)
    args = parser.parse_args()

    manifest = json.loads((args.capture_dir / "manifest.json").read_text())
    if manifest.get("symbol") != "BTCUSDT":
        raise SystemExit("FAIL: capture is not BTCUSDT")
    if manifest.get("market") != "USD-M":
        raise SystemExit("FAIL: capture is not Binance USDⓈ-M")
    if manifest.get("instrument") != "PERPETUAL":
        raise SystemExit("FAIL: capture is not BTCUSDT perpetual")
    if manifest.get("sequence_gaps", 0) != 0:
        raise SystemExit("FAIL: capture contains sequence gaps")
    if manifest.get("reconnects", 0) != 0:
        raise SystemExit("FAIL: capture contains reconnects")
    if manifest.get("bootstrap", {}).get("status") != "BRIDGED":
        raise SystemExit("FAIL: capture is not snapshot-bridged")

    config, config_sha = V20Config.load_authoritative(str(FROZEN_CONFIG))
    if config_sha != FROZEN_CONFIG_SHA256:
        raise SystemExit(
            f"FAIL: frozen config hash mismatch: {config_sha} != {FROZEN_CONFIG_SHA256}"
        )
    if config.symbol != "BTCUSDT":
        raise SystemExit("FAIL: frozen config symbol mismatch")
    if config.live_order_submission:
        raise SystemExit("FAIL: frozen config enables live order submission")

    snapshot = load_snapshot(args.capture_dir)
    depth, trades, counts = load_events(args.capture_dir)
    marks, funding = load_perpetual_auxiliary_events(args.capture_dir)
    if not marks or not funding:
        raise SystemExit("FAIL: perpetual capture lacks mark/funding observations")

    result = run_event_backtest(
        snapshot,
        depth,
        trades,
        config,
        mark_price_events=marks,
        funding_events=funding,
    )

    report = {
        "gate": "AFH01-BTCUSDT-USD-M-PERP-CAPTURE-INTEGRITY",
        "integrity": "PASS",
        "economic_certification": "PENDING_FORMAL_PROTOCOL",
        "deployment": "NO_DEPLOY",
        "research_reference": RESEARCH_REFERENCE,
        "config_sha256": config_sha,
        "capture": {
            "session_id": manifest.get("session_id"),
            "schema_version": manifest.get("schema_version"),
            **counts,
            "mark_price_events": len(marks),
            "funding_events": len(funding),
        },
        "result": {
            "fills": result.fills,
            "realized_pnl_usd": result.realized_pnl_usd,
            "inventory_mtm_usd": result.inventory_mtm_usd,
            "funding_pnl_usd": result.funding_pnl_usd,
            "net_pnl_usd": result.net_pnl_usd,
            "final_inventory": result.final_inventory,
            "inventory_max": result.inventory_max,
            "inventory_limit_breaches": result.inventory_limit_breaches,
            "fees_usd": result.fees_usd,
            "gross_spread_capture_usd": result.gross_spread_capture_usd,
            "attribution_residual_usd": result.attribution_residual_usd,
            "final_mark_price": result.final_mark_price,
        },
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
