"""V14 CLI — run the complete pipeline."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.v14.config import V14Config
from app.v14.pipeline import run_pipeline, calibrate, forward
from app.v14.gate import V14ProductionGate


def main():
    p = argparse.ArgumentParser(description="V14 BTCUSDT order-flow pipeline (10s horizon, maker/taker execution)")
    p.add_argument("action", choices=["calibrate", "forward", "gate", "full"])
    args = p.parse_args()
    cfg = V14Config()

    if args.action == "calibrate":
        result = run_pipeline("calibrate", cfg)
        print(f"Calibrate: {result['status']} | gross={result.get('calibration_gross_ev_bps', 0):.2f} net={result.get('calibration_net_ev_bps', 0):.2f} n={result.get('n_observations', 0)}")
    elif args.action == "forward":
        result = run_pipeline("forward", cfg)
        print(f"Forward: {result['status']} | net_ev={result.get('net_ev_bps', 0):.2f} p={result.get('p_value', 1):.4f} regimes={result.get('positive_regimes', 0)}/6")
    elif args.action == "gate":
        gate = V14ProductionGate(cfg)
        result = gate.evaluate()
        print(f"Gate: {result['gate_status']} | LIVE={result['live_order_submission']}")
        for name, check in result["checks"].items():
            print(f"  {name}: {check['status']}")
    elif args.action == "full":
        cal = run_pipeline("calibrate", cfg)
        print(f"Calibrate: {cal['status']}")
        fwd = run_pipeline("forward", cfg)
        print(f"Forward: {fwd['status']}")
        gate = V14ProductionGate(cfg)
        g = gate.evaluate()
        print(f"Gate: {g['gate_status']} | LIVE={g['live_order_submission']}")


if __name__ == "__main__":
    main()
