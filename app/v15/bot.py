"""V15 CLI — run the complete pipeline."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.v15.config import V15Config
from app.v15.pipeline import run_pipeline
from app.v15.gate import V15ProductionGate


def main():
    p = argparse.ArgumentParser(description="V15 BTCUSDT order-flow pipeline (execution-aware)")
    p.add_argument("action", choices=["calibrate", "forward", "gate", "full"])
    args = p.parse_args()
    cfg = V15Config()

    if args.action == "calibrate":
        result = run_pipeline("calibrate", cfg)
        print(f"Calibrate: {result['status']} | gross={result.get('gross_ev_bps', 0):.2f} net={result.get('net_ev_bps', 0):.2f} n={result.get('n_observations', 0)} trades={result.get('n_trades_calibration', 0)}")
    elif args.action == "forward":
        result = run_pipeline("forward", cfg)
        print(f"Forward: {result['status']} | net_ev={result.get('net_ev_bps', 0):.2f} p={result.get('p_value', 1):.4f} regimes={result.get('positive_regimes', 0)}/6 trades={result.get('n_trades', 0)}")
    elif args.action == "gate":
        gate = V15ProductionGate(cfg)
        result = gate.evaluate()
        print(f"Gate: {result['gate_status']} | LIVE={result['live_order_submission']}")
        for name, check in result["checks"].items():
            print(f"  {name}: {check['status']}")
    elif args.action == "full":
        cal = run_pipeline("calibrate", cfg)
        print(f"Calibrate: {cal['status']}")
        fwd = run_pipeline("forward", cfg)
        print(f"Forward: {fwd['status']}")
        gate = V15ProductionGate(cfg)
        g = gate.evaluate()
        print(f"Gate: {g['gate_status']} | LIVE={g['live_order_submission']}")


if __name__ == "__main__":
    main()
