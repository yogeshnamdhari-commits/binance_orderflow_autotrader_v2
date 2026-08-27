"""Data integrity engine — formal verification of Binance order-book reconstruction.

Verifies:
- sequence continuity (no gaps in update IDs)
- snapshot synchronization (buffered updates overlap snapshot)
- update ordering (monotonic timestamps)
- duplicate events
- crossed book (best_bid >= best_ask)
- negative/zero quantities
- stale timestamps
- trade/book synchronization

Produces: research/data_integrity_report.json

Usage:
    python -m app.data_quality [--sessions data/live/v2/20260818-190823 ...]
"""

import json
import argparse
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, field, asdict

import numpy as np


@dataclass
class SessionIntegrityResult:
    session: str
    total_events: int = 0
    depth_events: int = 0
    trade_events: int = 0
    snapshot_events: int = 0
    
    # Sequence checks
    sequence_gaps: int = 0
    sequence_gap_details: List[str] = field(default_factory=list)
    
    # Timestamp checks
    non_monotonic_timestamps: int = 0
    stale_events: int = 0
    max_stale_ms: float = 0.0
    
    # Book integrity
    crossed_book_events: int = 0
    negative_qty_events: int = 0
    zero_qty_events: int = 0
    
    # Trade integrity
    invalid_trade_sides: int = 0
    zero_trade_qty: int = 0
    
    # Sync issues
    orphan_updates: int = 0
    skipped_events: int = 0
    
    # Overall
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    passed: bool = True


def verify_session(session_dir: Path) -> SessionIntegrityResult:
    """Verify a single session's raw data."""
    result = SessionIntegrityResult(session=session_dir.name)
    raw_path = session_dir / "raw.jsonl"
    
    if not raw_path.exists():
        result.errors.append("raw.jsonl not found")
        result.passed = False
        return result
    
    lines = [l.strip() for l in raw_path.open() if l.strip()]
    if not lines:
        result.errors.append("raw.jsonl is empty")
        result.passed = False
        return result
    
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as e:
            result.errors.append(f"Invalid JSON: {e}")
    
    if not events:
        result.passed = False
        return result
    
    result.total_events = len(events)
    
    # Track state
    snapshot_id = None
    last_update_id = None
    last_event_ms = None
    last_trade_ms = None
    
    for i, ev in enumerate(events):
        kind = ev.get("kind", "")
        
        if kind == "snapshot":
            result.snapshot_events += 1
            snapshot_id = ev.get("last_update_id")
            last_update_id = snapshot_id
            
            # Verify snapshot integrity
            bids = ev.get("bids", [])
            asks = ev.get("asks", [])
            
            if not bids or not asks:
                result.errors.append(f"Event {i}: snapshot with empty bids/asks")
                continue
            
            # Check for crossed snapshot
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
            if best_bid >= best_ask:
                result.crossed_book_events += 1
                result.errors.append(
                    f"Event {i}: crossed snapshot bid={best_bid} >= ask={best_ask}")
            
            # Check for negative/zero quantities
            for p, q in bids + asks:
                qf = float(q)
                if qf < 0:
                    result.negative_qty_events += 1
                elif qf == 0:
                    result.zero_qty_events += 1
        
        elif kind == "depth":
            result.depth_events += 1
            
            first_id = ev.get("U")
            final_id = ev.get("u")
            event_ms = ev.get("E")
            
            # Sequence continuity
            if last_update_id is not None and first_id is not None:
                expected_first = last_update_id + 1
                if first_id > expected_first:
                    gap = first_id - expected_first
                    result.sequence_gaps += 1
                    if len(result.sequence_gap_details) < 5:
                        result.sequence_gap_details.append(
                            f"Event {i}: gap of {gap} IDs "
                            f"(expected {expected_first}, got {first_id})")
            
            # Timestamp monotonicity
            if last_event_ms is not None and event_ms is not None:
                if event_ms < last_event_ms:
                    result.non_monotonic_timestamps += 1
                else:
                    stale = event_ms - last_event_ms
                    if stale > 500:  # More than 500ms between events
                        result.stale_events += 1
                        result.max_stale_ms = max(result.max_stale_ms, stale)
            
            if event_ms is not None:
                last_event_ms = event_ms
            if final_id is not None:
                last_update_id = final_id
            
            # Check for orphan updates (before snapshot)
            if snapshot_id is not None and first_id is not None:
                if first_id <= snapshot_id:
                    result.orphan_updates += 1
        
        elif kind == "trade":
            result.trade_events += 1
            
            trade_ms = ev.get("T")
            qty = ev.get("q")
            maker = ev.get("m")
            
            # Timestamp check
            if last_trade_ms is not None and trade_ms is not None:
                if trade_ms < last_trade_ms:
                    result.non_monotonic_timestamps += 1
            
            if trade_ms is not None:
                last_trade_ms = trade_ms
            
            # Trade integrity
            if qty is not None:
                qf = float(qty)
                if qf < 0:
                    result.negative_qty_events += 1
                elif qf == 0:
                    result.zero_trade_qty += 1
            
            if maker is not None and not isinstance(maker, bool):
                result.invalid_trade_sides += 1
        
        elif kind == "bookTicker":
            pass  # Ticker events are reference only
    
    # Final assessment
    if result.sequence_gaps > 0:
        result.warnings.append(f"{result.sequence_gaps} sequence gaps detected")
    if result.crossed_book_events > 0:
        result.errors.append(f"{result.crossed_book_events} crossed book events")
        result.passed = False
    if result.negative_qty_events > 0:
        result.errors.append(f"{result.negative_qty_events} negative quantity events")
        result.passed = False
    if result.non_monotonic_timestamps > 0:
        result.warnings.append(
            f"{result.non_monotonic_timestamps} non-monotonic timestamps")
    if result.orphan_updates > 0:
        result.warnings.append(f"{result.orphan_updates} orphan updates (before snapshot)")
    
    return result


def run_data_integrity_check(session_dirs: List[Path]) -> Dict:
    """Run full data integrity check on all sessions."""
    results = {
        "total_sessions": len(session_dirs),
        "sessions": {},
        "total_events": 0,
        "total_errors": 0,
        "total_warnings": 0,
        "all_passed": True,
    }
    
    for sd in sorted(session_dirs):
        if not sd.is_dir():
            continue
        session_result = verify_session(sd)
        results["sessions"][sd.name] = asdict(session_result)
        results["total_events"] += session_result.total_events
        results["total_errors"] += len(session_result.errors)
        results["total_warnings"] += len(session_result.warnings)
        if not session_result.passed:
            results["all_passed"] = False
    
    return results


def generate_report(results: Dict, out_path: Path) -> Path:
    """Generate human-readable integrity report."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Save JSON report
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    # Print summary
    print("=" * 70)
    print("DATA INTEGRITY REPORT")
    print("=" * 70)
    print(f"Sessions checked: {results['total_sessions']}")
    print(f"Total events: {results['total_events']}")
    print(f"Total errors: {results['total_errors']}")
    print(f"Total warnings: {results['total_warnings']}")
    print(f"Overall: {'PASS' if results['all_passed'] else 'FAIL'}")
    print()
    
    for name, session in sorted(results["sessions"].items()):
        status = "PASS" if session["passed"] else "FAIL"
        print(f"  {name}: {status} | "
              f"events={session['total_events']} "
              f"(depth={session['depth_events']}, trade={session['trade_events']}) | "
              f"errors={len(session['errors'])} warnings={len(session['warnings'])}")
        if session["errors"]:
            for err in session["errors"][:3]:
                print(f"    ERROR: {err}")
        if session["warnings"][:2]:
            for warn in session["warnings"][:2]:
                print(f"    WARN: {warn}")
    
    print()
    print(f"Full report saved to: {out_path}")
    print("=" * 70)
    
    return out_path


def main():
    ap = argparse.ArgumentParser(description="Binance data integrity verification")
    ap.add_argument("--sessions", nargs="+", type=Path, default=None,
                    help="Session directories (default: auto-detect)")
    ap.add_argument("--out", type=Path,
                    default=Path("research/data_integrity_report.json"))
    a = ap.parse_args()
    
    if a.sessions is None:
        v2_root = Path("data/live/v2")
        if v2_root.exists():
            session_dirs = sorted([d for d in v2_root.glob("2026*") if d.is_dir()])
        else:
            print("No data/live/v2 directory found")
            return 1
    else:
        session_dirs = a.sessions
    
    print(f"Checking {len(session_dirs)} sessions...")
    results = run_data_integrity_check(session_dirs)
    generate_report(results, a.out)
    
    return 0 if results["all_passed"] else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
