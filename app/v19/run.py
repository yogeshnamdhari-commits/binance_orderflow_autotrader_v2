from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_v19_config
from .pipeline import write_evidence
from .replay import run_historical_replay


def main() -> None:
    parser = argparse.ArgumentParser(description="Run locked V19 historical L2 replay")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = load_v19_config(args.config)
    result = run_historical_replay(args.events, config)
    write_evidence(result, args.output)
    print(f"V19 gate={'PASS' if result['gate_pass'] else 'FAIL'} net_ev_bps={result['net_ev_bps']:.6f}")


if __name__ == "__main__":
    main()
