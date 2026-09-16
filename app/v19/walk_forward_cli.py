"""Walk-forward validation across multiple V19 captures."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

import numpy as np

from .config import load_v19_config
from .replay import run_historical_replay
from .pipeline import write_evidence


def find_capture_dirs(root: Path) -> list[Path]:
    if not root.exists():
        raise FileNotFoundError(root)
    dirs = []
    for path in sorted(root.iterdir()):
        if path.is_dir() and (path / "events.jsonl").exists() and (path / "snapshot.json").exists():
            manifest_path = path / "manifest.json"
            if manifest_path.exists():
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                bootstrap = manifest.get("bootstrap", {})
                if bootstrap.get("status") == "BRIDGED":
                    dirs.append(path)
    return dirs


def run_walk_forward(captures: Sequence[Path], config_path: Path, output: Path) -> dict[str, object]:
    config = load_v19_config(config_path)
    results = []
    for capture_dir in captures:
        events_path = capture_dir / "events.jsonl"
        if not events_path.exists():
            continue
        print(f"Running V19 on {capture_dir.name}...")
        result = run_historical_replay(events_path, config)
        result["capture_dir"] = capture_dir.name
        results.append(result)
        print(f"  net_ev_bps={result['net_ev_bps']:.4f} gate_pass={result['gate_pass']}")
    summary = {
        "config_hash": config.config_hash,
        "n_captures": len(results),
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run walk-forward validation across V19 captures")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--captures", type=Path, required=True)
    parser.add_argument("--min-folds", type=int, default=5)
    parser.add_argument("--min-test-events", type=int, default=1000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    capture_dirs = find_capture_dirs(args.captures)
    if not capture_dirs:
        raise ValueError(f"No valid captures found under {args.captures}")

    print(f"Found {len(capture_dirs)} valid capture(s)")
    summary = run_walk_forward(capture_dirs, args.config, args.output)
    print(f"Walk-forward results written to {args.output}")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
