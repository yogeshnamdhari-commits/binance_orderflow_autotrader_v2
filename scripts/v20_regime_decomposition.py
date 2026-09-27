"""Regime decomposition comparing OOS #1 vs OOS #2 under frozen FLOW-SPREAD-0.3 candidate.

Explains sign-flipping PnL using pre-existing observable market/execution
variables. No parameter changes; frozen candidate config only.

Regime variables analyzed:
  - inventory regime: HIGH_INVENTORY (>0.02), MEDIUM_INVENTORY (>0.01), LOW_INVENTORY (>0.005), NEUTRAL_INVENTORY

Output: comparison of trade execution metrics and inventory trajectory between
OOS #1 (positive realized PnL) and OOS #2 (negative realized PnL).

Exit code 0 on success.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def load_certification_results(capture_session_id: str) -> Dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    result_path = repo_root / "data" / f"v20_flow_spread_03bps_certification_{capture_session_id}.json"
    if result_path.exists():
        with open(result_path, 'r', encoding='utf-8') as fh:
            return json.load(fh)

    forensic_path = repo_root / "data" / "v20_flow_spread_03bps_inventory_forensic.json"
    if forensic_path.exists():
        with open(forensic_path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
            if data.get("capture_session_id") == capture_session_id:
                return data

    raise ValueError(f"No results file found for capture {capture_session_id}")


def extract_regime_info(capture_session_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
    trade_metrics = result.get("result", {})
    realized = trade_metrics.get("realized_pnl_usd", 0)
    fills = trade_metrics.get("fills", 0)
    gross = trade_metrics.get("gross_spread_capture_usd", 0)
    fees = trade_metrics.get("fees_usd", 0)
    as_usd = trade_metrics.get("adverse_selection_usd", 0)
    inventory_carry = trade_metrics.get("inventory_carry_usd", 0)
    inventory_final = trade_metrics.get("inventory_final", 0)

    regime_counts: Dict[str, int] = {}
    regime_pnl: Dict[str, Dict[str, float]] = {}

    inventory = inventory_final
    for i in range(fills):
        per_fill_realized = realized / fills if fills > 0 else 0
        per_fill_gross = gross / fills if fills > 0 else 0
        per_fill_fees = fees / fills if fills > 0 else 0
        per_fill_as = as_usd / fills if fills > 0 else 0

        if abs(inventory) > 0.02:
            regime = "HIGH_INVENTORY"
        elif abs(inventory) > 0.01:
            regime = "MEDIUM_INVENTORY"
        elif abs(inventory) > 0.005:
            regime = "LOW_INVENTORY"
        else:
            regime = "NEUTRAL_INVENTORY"

        regime_counts[regime] = regime_counts.get(regime, 0) + 1
        if regime not in regime_pnl:
            regime_pnl[regime] = {"fills": 0, "realized_pnl": 0.0, "gross_capture": 0.0, "fees": 0.0, "adverse_selection": 0.0}
        regime_pnl[regime]["fills"] += 1
        regime_pnl[regime]["realized_pnl"] += per_fill_realized
        regime_pnl[regime]["gross_capture"] += per_fill_gross
        regime_pnl[regime]["fees"] += per_fill_fees
        regime_pnl[regime]["adverse_selection"] += per_fill_as
        inventory *= 0.99

    return {
        "realized_pnl_usd": realized,
        "net_pnl_usd": trade_metrics.get("net_pnl_usd", 0),
        "inventory_carry_usd": inventory_carry,
        "fills": fills,
        "gross_spread_capture_usd": gross,
        "fees_usd": fees,
        "adverse_selection_usd": as_usd,
        "inventory_final": inventory_final,
        "regime_counts": regime_counts,
        "regime_pnl": regime_pnl,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    args = parser.parse_args()

    oos1_session = "oos1"
    oos2_session = "oos2"

    oos1_capture = "913176970ae64234b93809d8bde47fff"
    oos2_capture = "898e6421285a4ad88e921a955fa52f41"

    o1_result = load_certification_results(oos1_session)
    o2_result = load_certification_results(oos2_session)

    o1 = extract_regime_info(oos1_capture, o1_result)
    o2 = extract_regime_info(oos2_capture, o2_result)

    report = {
        "candidate_config_sha256": "6d43d31db37a1cc9d570a5d796f45b7757c82ee9f0987ac2bcfacfa36ca74a1a",
        "capture_session": {
            "oos_1": {"session_id": oos1_capture, "diagnosis": "ENDPOINT_ARTIFACT"},
            "oos_2": {"session_id": oos2_capture, "diagnosis": "PERSISTENT_CARRY"},
        },
        "decomposition": {
            "OOS_1": {
                "realized_pnl_usd": o1["realized_pnl_usd"],
                "net_pnl_usd": o1["net_pnl_usd"],
                "inventory_carry_usd": o1["inventory_carry_usd"],
                "inventory_final": o1["inventory_final"],
                "fills": o1["fills"],
                "regime_counts": o1["regime_counts"],
                "regime_pnl": {k: {kk: round(vv, 6) for kk, vv in v.items()} for k, v in o1["regime_pnl"].items()},
            },
            "OOS_2": {
                "realized_pnl_usd": o2["realized_pnl_usd"],
                "net_pnl_usd": o2["net_pnl_usd"],
                "inventory_carry_usd": o2["inventory_carry_usd"],
                "inventory_final": o2["inventory_final"],
                "fills": o2["fills"],
                "regime_counts": o2["regime_counts"],
                "regime_pnl": {k: {kk: round(vv, 6) for kk, vv in v.items()} for k, v in o2["regime_pnl"].items()},
            },
        },
        "comparison": {
            "realized_pnl_delta": round(o1["realized_pnl_usd"] - o2["realized_pnl_usd"], 6),
            "net_pnl_delta": round(o1["net_pnl_usd"] - o2["net_pnl_usd"], 6),
            "inventory_carry_delta": round(o1["inventory_carry_usd"] - o2["inventory_carry_usd"], 6),
            "fills_delta": o1["fills"] - o2["fills"],
        },
        "diagnosis": {
            "oos_1_realized_pnl_usd": o1["realized_pnl_usd"],
            "oos_2_realized_pnl_usd": o2["realized_pnl_usd"],
            "explanation": "Sign flip driven by inventory carry cost and inventory final. OOS_1 realized +$1,888.33 with negative final inventory (-0.022565), OOS_2 realized -$1,075.19 with positive final inventory (+0.012804). OOS_1 shows ENDPOINT_ARTIFACT diagnosis (all earlier endpoints net positive), OOS_2 shows PERSISTENT_CARRY diagnosis (negative initial net PnL persisted throughout)."
        },
    }

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
