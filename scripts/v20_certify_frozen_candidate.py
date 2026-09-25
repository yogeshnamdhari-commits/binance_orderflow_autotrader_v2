"""Deterministic certification gate for a FROZEN V20 candidate.

Unlike v20_performance_certify.py, which searches a parameter grid on a
chronological train/validation split, this runner accepts a single frozen
candidate configuration and evaluates it exactly once against a single
untouched OOS capture. No parameter selection happens here.

The artifact binds four fingerprints so the result is reproducible:

  CANDIDATE  exact Git commit + exact config file + exact config SHA-256
  DATASET    exact capture directory + manifest + snapshot + events SHA-256
  RESULT     deterministic economic gates
  CERTIFICATION  PASS / FAIL with per-rule breakdown

Exit code is 0 only when every gate passes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.mm.config import V20Config, config_sha256
from app.mm.event_backtest import run_event_backtest
from scripts.v20_event_backtest_capture import load_snapshot, load_events


def _sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, help="frozen candidate config JSON")
    parser.add_argument("--capture", required=True, help="OOS capture directory")
    parser.add_argument("--out", default=None, help="output JSON path")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    capture_dir = Path(args.capture)
    if not capture_dir.is_absolute():
        capture_dir = repo_root / capture_dir

    # --- CANDIDATE fingerprint -------------------------------------------
    candidate, candidate_sha = V20Config.load_authoritative(args.candidate)
    if candidate.live_order_submission:
        raise RuntimeError("candidate must have live_order_submission=false")
    git_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo_root
    ).decode().strip()
    git_short = git_commit[:12]

    # --- DATASET fingerprint --------------------------------------------
    manifest_path = capture_dir / "manifest.json"
    snapshot_path = capture_dir / "snapshot.json"
    events_path = capture_dir / "events.jsonl"
    for p in (manifest_path, snapshot_path, events_path):
        if not p.is_file():
            raise FileNotFoundError(f"missing capture file: {p}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("bootstrap", {}).get("status") != "BRIDGED":
        raise RuntimeError("capture bootstrap is not BRIDGED; refusing to certify")
    if str(manifest.get("symbol", "")).upper() != "BTCUSDT":
        raise RuntimeError(f"capture symbol is not BTCUSDT: {manifest.get('symbol')!r}")

    snapshot = load_snapshot(capture_dir)
    depth, trades, counts = load_events(capture_dir)

    # --- RESULT ----------------------------------------------------------
    result = run_event_backtest(snapshot, depth, trades, candidate)
    if abs(result.attribution_residual_usd) > 1e-6:
        raise RuntimeError(
            f"attribution residual {result.attribution_residual_usd} is not reconciled"
        )

    # --- DETERMINISTIC ECONOMIC GATES ------------------------------------
    gates = {
        "realized_pnl_positive": result.realized_pnl_usd > 0,
        "net_pnl_positive": result.net_pnl_usd > 0,
        "inventory_within_limit": result.inventory_max <= candidate.max_position_notional_usd + 1e-6,
        "no_inventory_breaches": result.inventory_limit_breaches == 0,
        "sufficient_fills": result.fills >= 100,
        "gross_capture_positive": result.gross_spread_capture_usd > 0,
        "attribution_reconciled": abs(result.attribution_residual_usd) <= 1e-6,
    }
    certified = all(gates.values())

    report = {
        "certification": {
            "status": "PERFORMANCE_CERTIFIED" if certified else "NOT_CERTIFIED",
            "git_commit": git_commit,
            "git_commit_short": git_short,
            "candidate_config": args.candidate,
            "candidate_config_sha256": candidate_sha,
            "candidate_fingerprint": candidate.canonical_dict(),
            "capture_dir": str(capture_dir.relative_to(repo_root) if capture_dir.is_absolute() else capture_dir),
            "capture_session_id": manifest.get("session_id"),
            "capture_manifest_sha256": _sha256_file(manifest_path),
            "capture_snapshot_sha256": _sha256_file(snapshot_path),
            "capture_events_sha256": _sha256_file(events_path),
            "capture_start_ns": manifest.get("start_ns"),
            "capture_end_ns": manifest.get("end_ns"),
            "capture_duration_sec": round(
                (manifest["end_ns"] - manifest["start_ns"]) / 1e9, 3
            ) if manifest.get("end_ns") and manifest.get("start_ns") else None,
            "capture_event_count": manifest.get("event_count"),
            "capture_bootstrap_status": manifest.get("bootstrap", {}).get("status"),
            "capture_snapshot_source": manifest.get("bootstrap", {}).get("snapshot_source"),
            "capture_reconnect_markers": counts.get("reconnect_markers", 0),
            "capture_documented_gaps_skipped": counts.get("documented_gaps_skipped", 0),
            "gates": gates,
            "gate_count_pass": sum(1 for v in gates.values() if v),
            "gate_count_total": len(gates),
        },
        "result": {
            "fills": result.fills,
            "gross_spread_capture_usd": round(result.gross_spread_capture_usd, 6),
            "fees_usd": round(result.fees_usd, 6),
            "realized_pnl_usd": round(result.realized_pnl_usd, 6),
            "net_pnl_usd": round(result.net_pnl_usd, 6),
            "inventory_carry_usd": round(result.inventory_carry_usd, 6),
            "inventory_mtm_usd": round(result.inventory_mtm_usd, 6),
            "adverse_selection_usd": round(result.adverse_selection_usd, 6),
            "avg_adverse_selection_bps": round(result.avg_adverse_selection_bps, 6),
            "inventory_max": round(result.inventory_max, 6),
            "inventory_final": round(result.final_inventory, 6),
            "inventory_limit_breaches": result.inventory_limit_breaches,
            "pnl_per_fill": round(result.realized_pnl_usd / result.fills, 6) if result.fills > 0 else None,
            "gross_capture_per_fill": round(
                result.gross_spread_capture_usd / result.fills, 8
            ) if result.fills > 0 else None,
            "attribution_residual_usd": round(result.attribution_residual_usd, 12),
        },
    }

    if args.out:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = repo_root / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if certified else 2


if __name__ == "__main__":
    sys.exit(main())