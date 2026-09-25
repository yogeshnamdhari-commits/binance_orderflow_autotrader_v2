"""Forensic reconciliation of inventory carry vs endpoint-marking artifact.

The frozen flow-spread 0.3bps candidate shows:
  realized PnL  +$1,888.33
  inventory_carry  -$1,892.22
  net PnL       -$6.53

The net PnL gate fails. But -$1,892.22 inventory carry can mean two
economically different things:

  A. Endpoint artifact: the strategy held a small open position at the
     capture endpoint and mark-to-market penalized it. The trading was
     profitable; the accounting convention just closed the window mid-
     position. Net PnL would be positive at any earlier endpoint.

  B. Persistent carry: the strategy accumulated and held inventory for
     most of the session, and the carry cost is real, not an artifact.

This tool does NOT change the candidate. It replays the frozen config
once and reports the inventory trajectory plus net PnL at multiple
hypothetical endpoints, so the distinction is measurable rather than
inferred.

Exit code is always 0: this is an analysis report, not a certification
gate. Certification status is NOT changed by this output.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.mm.config import V20Config
from app.mm.event_backtest import run_event_backtest
from scripts.v20_event_backtest_capture import load_snapshot, load_events


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--capture", required=True)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    capture_dir = Path(args.capture)
    if not capture_dir.is_absolute():
        capture_dir = repo_root / capture_dir

    candidate, candidate_sha = V20Config.load_authoritative(args.candidate)
    snapshot = load_snapshot(capture_dir)
    depth, trades, counts = load_events(capture_dir)

    # Single replay. Realized PnL is cash from fills; inventory_mtm is the
    # mark-to-market of the residual open position at the capture endpoint.
    # The question is whether the residual is an endpoint artifact or
    # persistent carry, so we inspect the trajectory rather than re-tune.
    result = run_event_backtest(snapshot, depth, trades, candidate)
    traj = result.inventory_trajectory

    if not traj:
        print(json.dumps({"error": "no inventory trajectory"}, indent=2))
        return 0

    # Mid price series indexed by timestamp for MTM projection.
    # IMPORTANT: L2Update.bids/asks are raw event arrays and are NOT
    # guaranteed to be price-sorted. The best bid is the max price with
    # positive qty, and the best ask is the min price with positive qty.
    # This matches the backtest's own book-derived mid exactly
    # (max(bids.keys()) / min(asks.keys())).
    mid_by_ts = {}
    for d in depth:
        if not d.bids or not d.asks:
            continue
        bid_prices = [p for p, q in d.bids if q > 0]
        ask_prices = [p for p, q in d.asks if q > 0]
        if not bid_prices or not ask_prices:
            continue
        best_bid = max(bid_prices)
        best_ask = min(ask_prices)
        if best_bid <= 0 or best_ask <= 0 or best_bid >= best_ask:
            continue
        mid_by_ts[d.timestamp_ns] = (best_bid + best_ask) / 2.0
    sorted_mids = sorted(mid_by_ts.items())

    def mid_at(ts_ns: int) -> float:
        # Latest mid at or before ts_ns; fall back to nearest.
        best = None
        for t, m in sorted_mids:
            if t <= ts_ns:
                best = m
            else:
                break
        if best is None and sorted_mids:
            best = sorted_mids[0][1]
        return best or 0.0

    # Net PnL if the strategy had liquidated at each trajectory point,
    # assuming the same realized cash. This is a hypothetical projection
    # to distinguish endpoint artifact from persistent carry.
    fractions = [0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 1.00]
    endpoints = []
    for f in fractions:
        idx = min(len(traj) - 1, max(0, int(len(traj) * f)))
        ts, inv = traj[idx]
        mtm = inv * mid_at(ts)
        endpoints.append({
            "fraction": f,
            "endpoint_index": idx,
            "endpoint_ts_ns": ts,
            "inventory_at_endpoint": round(inv, 6),
            "mid_at_endpoint": round(mid_at(ts), 6),
            "mtm_at_endpoint": round(mtm, 6),
            "net_at_endpoint": round(result.realized_pnl_usd + mtm, 6),
        })

    # Inventory persistence: fraction of trajectory where |inventory| > 0.
    nonzero = sum(1 for _, inv in traj if abs(inv) > 1e-9)
    persistence = nonzero / len(traj) if traj else 0.0

    # Max absolute inventory and when it occurred.
    max_inv = max((abs(inv) for _, inv in traj), default=0.0)
    max_inv_ts = next((ts for ts, inv in traj if abs(inv) >= max_inv - 1e-9), None)

    # Final inventory (the binding MTM term).
    final_ts, final_inv = traj[-1]

    # Diagnosis: if net PnL is positive at every earlier endpoint, the
    # negative net is an endpoint artifact. Otherwise it is persistent.
    earlier = [e for e in endpoints if e["fraction"] < 1.0]
    all_positive_earlier = bool(earlier) and all(
        e["net_at_endpoint"] > 0 for e in earlier
    )

    report = {
        "candidate_config_sha256": candidate_sha,
        "capture_session_id": capture_dir.name,
        "realized_pnl_usd": round(result.realized_pnl_usd, 6),
        "inventory_mtm_usd": round(result.inventory_mtm_usd, 6),
        "net_pnl_usd": round(result.net_pnl_usd, 6),
        "inventory_carry_usd": round(result.inventory_carry_usd, 6),
        "final_inventory": round(final_inv, 6),
        "trajectory_points": len(traj),
        "inventory_persistence_fraction": round(persistence, 6),
        "max_abs_inventory": round(max_inv, 6),
        "max_abs_inventory_ts_ns": max_inv_ts,
        "endpoints": endpoints,
        "all_earlier_endpoints_net_positive": all_positive_earlier,
        "diagnosis": (
            "ENDPOINT_ARTIFACT"
            if all_positive_earlier
            else "PERSISTENT_CARRY"
        ),
    }

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())