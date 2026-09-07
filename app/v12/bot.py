#!/usr/bin/env python3
"""V12 bot CLI — explicit modes for research/backtest/forward/paper/testnet/production.

Production must refuse to start if any gate is not PASS.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import Config
from app.v12.config import V12Config
from app.v12.pipeline import run_v12_calibration, run_v12_forward
from app.v12.risk import V12RiskEngine, V12RiskConfig, RiskState
from app.v12.position import V12PositionEngine
from app.v12.orders import V12OrderManager
from app.v12.exit import V12ExitEngine, V12ExitConfig
from app.v12.execution_model import V12ExecutionModel
from app.v12.capture import capture_session


def _check_forward_gate(output_dir: Path) -> tuple[bool, str]:
    gate_path = output_dir / "v12_forward_result.json"
    if not gate_path.exists():
        return False, "forward validation result not found"
    fwd = json.loads(gate_path.read_text(encoding="utf-8"))
    if fwd.get("status") != "PASS":
        return False, f"forward gate FAILED ({fwd.get('status')})"
    return True, "forward gate PASS"


def mode_research(args):
    """Run research pipeline (calibration + forward)."""
    from app.v12.pipeline import main as pipeline_main
    sys.argv = ["v12_pipeline", "--mode", "full", "--calibration-dir", args.calibration_dir, "--forward-dir", args.forward_dir, "--output-dir", args.output_dir]
    return pipeline_main()


def mode_calibrate(args):
    """Run calibration only."""
    config = V12Config()
    cal_dirs = sorted([d for d in Path(args.calibration_dir).iterdir() if d.is_dir()])
    if not cal_dirs:
        print("ERROR: no calibration sessions found", file=sys.stderr)
        return 1
    run_v12_calibration(cal_dirs, Path(args.output_dir), config)
    return 0


def mode_forward(args):
    """Run forward validation only."""
    config = V12Config()
    fwd_dirs = sorted([d for d in Path(args.forward_dir).iterdir() if d.is_dir()])
    if not fwd_dirs:
        print("ERROR: no forward sessions found", file=sys.stderr)
        return 1
    model_path = Path(args.output_dir) / "v12_frozen_model.joblib"
    if not model_path.exists():
        print("ERROR: frozen model not found", file=sys.stderr)
        return 1
    fwd_result = run_v12_forward(fwd_dirs, model_path, Path(args.output_dir), config)
    return 0 if fwd_result["status"] == "PASS" else 2


def mode_capture(args):
    """Capture market data session."""
    session_dir = capture_session(
        symbol=args.symbol,
        output_dir=args.output_dir,
        duration_seconds=parse_duration(args.duration),
    )
    print(f"Session captured: {session_dir}")
    return 0


def parse_duration(s: str) -> int:
    import re
    match = re.fullmatch(r"(\d+)([smh])", s.strip().lower())
    if not match:
        raise ValueError("duration must be integer + s/m/h")
    amount = int(match.group(1))
    mult = {"s": 1, "m": 60, "h": 3600}[match.group(2)]
    return amount * mult


def mode_paper(args):
    """Run paper trading against live data with simulated execution."""
    ok, reason = _check_forward_gate(Path(args.output_dir))
    if not ok:
        print(f"ERROR: paper trading requires forward gate PASS — {reason}", file=sys.stderr)
        return 1

    from app.v12.model import V12SignalModel
    from app.v12.paper_runtime import V12PaperRuntime, V12PaperConfig

    model_path = Path(args.output_dir) / "v12_frozen_model.joblib"
    model = V12SignalModel.load(model_path)
    runtime = V12PaperRuntime(model=model, paper_cfg=V12PaperConfig(
        audit_log_path=str(Path(args.output_dir) / "paper_audit.jsonl"),
    ))
    print(f"V12 PAPER TRADING STARTED (model val_auc={model._val_auc:.4f})")
    print("All fills simulated. No live orders.")
    try:
        runtime.run_snapshot_loop(parse_duration(args.duration))
    except KeyboardInterrupt:
        print("\nStopping paper trading...")
        if runtime._audit:
            runtime._audit.close()
    return 0


def mode_testnet(args):
    """Run testnet execution validation (requires paper success)."""
    paper_path = Path(args.output_dir) / "paper_summary.json"
    if not paper_path.exists():
        print("ERROR: paper trading summary not found", file=sys.stderr)
        return 1

    import os
    api_key = os.environ.get("BINANCE_API_KEY", "")
    api_secret = os.environ.get("BINANCE_API_SECRET", "")
    if not api_key or not api_secret:
        print("ERROR: set BINANCE_API_KEY and BINANCE_API_SECRET for testnet", file=sys.stderr)
        return 1

    from app.v12.testnet import run_testnet_validation
    result = run_testnet_validation(
        api_key=api_key, api_secret=api_secret, symbol=args.symbol,
        output_path=Path(args.output_dir) / "v12_testnet_result.json",
    )
    print(f"Testnet plumbing: auth={result.auth_ok} submit={result.submit_ok} "
          f"cancel={result.cancel_ok} position={result.position_ok} "
          f"reconcile={result.reconcile_ok}")
    if result.errors:
        print(f"Errors: {result.errors}")
    return 0 if all([result.auth_ok, result.submit_ok, result.cancel_ok,
                     result.position_ok, result.reconcile_ok]) else 1


def mode_production(args):
    """Production mode - LOCKED until all gates PASS."""
    from app.v12.production import ProductionGate, LIVE_ORDER_SUBMISSION
    gate = ProductionGate(Path(args.output_dir))
    gates = gate.evaluate()
    print("V12 PRODUCTION GATE STATUS")
    print("=" * 50)
    for k in gate.REQUIRED_KEYS:
        v = gates.get(k, "NOT_STARTED")
        status = "PASS" if v == "PASS" else v
        print(f"  {k}: {status}")
    print(f"\nLIVE_ORDER_SUBMISSION: {LIVE_ORDER_SUBMISSION}")
    print("=" * 50)
    if not LIVE_ORDER_SUBMISSION:
        print("PRODUCTION REMAINS LOCKED: LIVE_ORDER_SUBMISSION is hard-FALSE in code (Rule 28)")
        return 1
    ready, reason = gate.is_production_ready()
    if not ready:
        print(f"PRODUCTION REMAINS LOCKED: {reason}")
        return 1
    print("All gates PASS. Production executor ready.")
    return 0


def mode_gates(args):
    """Display current gate status."""
    gate_path = Path(args.output_dir) / "v12_forward_result.json"
    if not gate_path.exists():
        print("No forward validation result found")
        return 0
    with open(gate_path) as f:
        gate = json.load(f)
    print("V12 PRODUCTION GATE STATUS")
    print("=" * 50)
    print(f"Overall: {gate.get('status', 'UNKNOWN')}")
    print(f"Net EV: {gate.get('mean_net_ev_bps', 0):.4f} bps")
    print(f"95% CI: [{gate.get('ci_95_lower', 0):.4f}, {gate.get('ci_95_upper', 0):.4f}]")
    print(f"p-value: {gate.get('p_value', 1):.4f}")
    print(f"Funding income: {gate.get('funding_income_bps', 0):.4f} bps")
    print()
    for k, v in gate.get("gate_conditions", {}).items():
        status = "PASS" if v else "FAIL"
        print(f"  {k}: {status}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="V12 bot CLI")
    ap.add_argument("--mode", choices=["research", "calibrate", "forward", "capture", "paper", "testnet", "production", "gates"], required=True)
    ap.add_argument("--calibration-dir", type=Path, default=Path("data/v12/calibration"))
    ap.add_argument("--forward-dir", type=Path, default=Path("data/v12/forward"))
    ap.add_argument("--output-dir", type=Path, default=Path("archive/v12"))
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--duration", default="300s")
    args = ap.parse_args(argv)

    modes = {
        "research": mode_research,
        "calibrate": mode_calibrate,
        "forward": mode_forward,
        "capture": mode_capture,
        "paper": mode_paper,
        "testnet": mode_testnet,
        "production": mode_production,
        "gates": mode_gates,
    }

    return modes[args.mode](args)


if __name__ == "__main__":
    sys.exit(main())