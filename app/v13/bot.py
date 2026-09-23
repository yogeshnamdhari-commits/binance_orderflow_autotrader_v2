"""V13 bot CLI — research/calibrate/forward/capture/production-gate."""
from __future__ import annotations

import argparse
import json
import sys
import re
from pathlib import Path

from app.v13.config import V13Config
from app.v13.pipeline import run_v13_calibration, run_v13_forward
from app.v12.capture import capture_session


def parse_duration(s: str) -> int:
    match = re.fullmatch(r"(\d+)([smh])", s.strip().lower())
    if not match:
        raise ValueError("duration must be integer + s/m/h")
    amount = int(match.group(1))
    mult = {"s": 1, "m": 60, "h": 3600}[match.group(2)]
    return amount * mult


def main(argv=None):
    ap = argparse.ArgumentParser(description="V13 bot CLI")
    ap.add_argument("--mode", choices=["research", "calibrate", "forward", "capture", "gates"], required=True)
    ap.add_argument("--calibration-dir", type=Path, default=Path("data/v13/calibration"))
    ap.add_argument("--forward-dir", type=Path, default=Path("data/v13/forward"))
    ap.add_argument("--output-dir", type=Path, default=Path("archive/v13"))
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--duration", default="60s")
    args = ap.parse_args(argv)

    config = V13Config()

    if args.mode == "research":
        cal_dirs = sorted([d for d in args.calibration_dir.iterdir() if d.is_dir()])
        if not cal_dirs:
            print("ERROR: no calibration sessions", file=sys.stderr); return 1
        run_v13_calibration(cal_dirs, args.output_dir, config)
        fwd_dirs = sorted([d for d in args.forward_dir.iterdir() if d.is_dir()])
        if not fwd_dirs:
            print("ERROR: no forward sessions", file=sys.stderr); return 1
        result = run_v13_forward(fwd_dirs, args.output_dir / "v13_frozen_model.joblib", args.output_dir, config)
        print(f"\nV13 RESULT: {result['status']} | Net EV: {result['mean_net_ev_bps']:.4f} bps")
        return 0 if result["status"] == "PASS" else 2

    if args.mode == "calibrate":
        cal_dirs = sorted([d for d in args.calibration_dir.iterdir() if d.is_dir()])
        if not cal_dirs:
            print("ERROR: no calibration sessions", file=sys.stderr); return 1
        run_v13_calibration(cal_dirs, args.output_dir, config)
        return 0

    if args.mode == "forward":
        fwd_dirs = sorted([d for d in args.forward_dir.iterdir() if d.is_dir()])
        if not fwd_dirs:
            print("ERROR: no forward sessions", file=sys.stderr); return 1
        model_path = args.output_dir / "v13_frozen_model.joblib"
        if not model_path.exists():
            print("ERROR: frozen model not found", file=sys.stderr); return 1
        result = run_v13_forward(fwd_dirs, model_path, args.output_dir, config)
        return 0 if result["status"] == "PASS" else 2

    if args.mode == "capture":
        r = capture_session(args.symbol, args.output_dir, parse_duration(args.duration))
        print(f"Session captured: {r.session_dir}")
        return 0

    if args.mode == "gates":
        from app.v13.production import V13ProductionGate
        gate = V13ProductionGate(args.output_dir)
        gates = gate.evaluate()
        print("V13 PRODUCTION GATE STATUS")
        for k in gate.REQUIRED_KEYS:
            print(f"  {k}: {gates.get(k, 'NOT_STARTED')}")
        ready, reason = gate.is_production_ready()
        print(f"\nReady: {ready}")
        if not ready:
            print(f"Reason: {reason}")
        return 0 if ready else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
