"""V16 CLI — run the complete research and deployment-preflight pipeline."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.v16.config import V16Config
from app.v16.pipeline import run_pipeline
from app.v16.gate import V16ProductionGate
from app.v16.production_preflight import ProductionPreflight


def main():
    p = argparse.ArgumentParser(description="V16 BTCUSDT order-flow pipeline (queue-aware, event-time)")
    p.add_argument("action", choices=["calibrate", "forward", "gate", "preflight", "full"])
    args = p.parse_args()
    cfg = V16Config()

    if args.action == "calibrate":
        result = run_pipeline("calibrate", cfg)
        print(f"Calibrate: {result['status']} | gross={result.get('gross_ev_bps', 0):.2f} net={result.get('net_ev_bps', 0):.2f} n={result.get('n_observations', 0)} trades={result.get('n_trades_calibration', 0)}")
    elif args.action == "forward":
        result = run_pipeline("forward", cfg)
        print(f"Forward: {result['status']} | net_ev={result.get('net_ev_bps', 0):.2f} p={result.get('p_value', 1):.4f} trades={result.get('n_trades', 0)}")
    elif args.action == "gate":
        gate = V16ProductionGate(cfg)
        result = gate.evaluate()
        print(f"Gate: {result['gate_status']} | LIVE={result['live_order_submission']}")
        for name, check in result["checks"].items():
            print(f"  {name}: {check['status']}")
    elif args.action == "preflight":
        result = ProductionPreflight(
            live_order_submission=cfg.live_trading_enabled,
            production_authorized=False,
        ).evaluate()
        print(f"Production preflight: {'READY' if result.ready else 'LOCKED'} | LIVE={result.live_order_submission}")
        for name, status in result.checks.items():
            print(f"  {name}: {status}")
    elif args.action == "full":
        cal = run_pipeline("calibrate", cfg)
        print(f"Calibrate: {cal['status']}")
        fwd = run_pipeline("forward", cfg)
        print(f"Forward: {fwd['status']}")
        gate = V16ProductionGate(cfg)
        g = gate.evaluate()
        print(f"Gate: {g['gate_status']} | LIVE={g['live_order_submission']}")
        preflight = ProductionPreflight(
            live_order_submission=cfg.live_trading_enabled,
            production_authorized=False,
        ).evaluate()
        print(f"Preflight: {'READY' if preflight.ready else 'LOCKED'}")


if __name__ == "__main__":
    main()
