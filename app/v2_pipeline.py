"""V2 research pipeline driver (build -> labels -> calibrate -> validate)."""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from . import v2_features, v2_labels, v2_model, v2_validation

DEFAULT_OUT = Path("data/hist/research")


def cmd_build(args):
    return v2_features.build_session_features(args.out, args.sessions)


def cmd_labels(args):
    return v2_labels.write_labels(args.out, pd.read_parquet(args.features))


def cmd_calibrate(args):
    m, c = v2_model.calibrate(args.features, args.outdir)
    print(json.dumps({"model": str(args.outdir / "v2_model.json"),
                      "combined_train_r2": c["combined_train"]}, indent=1))
    return args.outdir / "v2_model.json"


def cmd_validate(args):
    r = v2_validation.validate(args.model, args.cost, args.features, args.outdir,
                               args.horizon_ms, args.notional_usd, args.style)
    print(json.dumps({"verdict": r["verdict"],
                      "oos_net_expectancy_bps": r["blocks"]["oos"]["net_expectancy_bps"]}, indent=1))
    return args.outdir / "v2_oos.json"


def main(argv=None):
    ap = argparse.ArgumentParser(description="V2 order-flow research pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("build", help="sessions -> features parquet")
    p.add_argument("sessions", nargs="+", type=Path)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT / "v2_features.parquet")
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("labels", help="features -> labels parquet")
    p.add_argument("--features", type=Path, default=DEFAULT_OUT / "v2_features.parquet")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT / "v2_labels.parquet")
    p.set_defaults(fn=cmd_labels)

    p = sub.add_parser("calibrate", help="train the frozen linear model (once)")
    p.add_argument("--features", type=Path, default=DEFAULT_OUT / "v2_features.parquet")
    p.add_argument("--outdir", type=Path, default=DEFAULT_OUT)
    p.set_defaults(fn=cmd_calibrate)

    p = sub.add_parser("validate", help="untouched-OOS validation")
    p.add_argument("--model", type=Path, default=DEFAULT_OUT / "v2_model.json")
    p.add_argument("--cost", type=Path, default=Path("data/hist/research/execution_calibration.json"))
    p.add_argument("--features", type=Path, default=DEFAULT_OUT / "v2_features.parquet")
    p.add_argument("--outdir", type=Path, default=DEFAULT_OUT)
    p.add_argument("--horizon-ms", type=int, default=500)
    p.add_argument("--notional-usd", type=float, default=1000.0)
    p.add_argument("--style", default="taker", choices=("taker", "maker"))
    p.set_defaults(fn=cmd_validate)

    args = ap.parse_args(argv)
    return 0 if args.fn(args) else 1


if __name__ == "__main__":
    sys.exit(main())