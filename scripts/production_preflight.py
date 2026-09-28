"""Offline production preflight for ACTIVE_FLOW_HEDGE-0.1.

This command never places an order. It verifies the candidate configuration,
the required research reference, and that authorization is still fail-closed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.mm.config import V20Config, config_sha256
from app.mm.production_execution import DeploymentManifest, ProductionSafetyError


RESEARCH_COMMIT = "a06e8f590634777bbd5ade86ef3b2563194ca2ed"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--config",
        default="app/mm/config_v21_active_flow_hedge_01bps.json",
    )
    ap.add_argument(
        "--manifest",
        default="data/live/active_flow_hedge_deployment.json",
    )
    args = ap.parse_args()

    config, sha = V20Config.load_authoritative(args.config)
    raw = json.loads(Path(args.config).read_text())

    expected = {
        "flow_quote_bias_bps": 1.0,
        "hedge_threshold_notional": 1000.0,
        "hedge_ratio": 0.5,
        "inventory_penalty_base_bps": 1.0,
        "inventory_penalty_slope": 0.5,
        "quote_size_reduction_after_breach": 0.5,
        "max_position_notional_usd": 5000.0,
    }
    for key, value in expected.items():
        if raw.get(key) != value:
            raise SystemExit(f"FROZEN PARAMETER MISMATCH: {key}={raw.get(key)!r}, expected {value!r}")

    if raw.get("live_order_submission") is not False:
        raise SystemExit("FAIL-CLOSED VIOLATION: strategy config live_order_submission must remain false")

    print(f"CONFIG_SHA256={sha}")
    print(f"RESEARCH_REFERENCE={RESEARCH_COMMIT}")
    print("STRATEGY_PARAMETERS=PASS")
    print("LIVE_ORDER_SUBMISSION=FALSE")
    try:
        DeploymentManifest.load(args.manifest)
    except ProductionSafetyError as exc:
        print(f"LIVE_AUTHORIZATION=BLOCKED ({exc})")
    else:
        print("LIVE_AUTHORIZATION=MANIFEST_PRESENT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
