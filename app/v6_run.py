"""V6 orchestrator — end-to-end V6 research extension pipeline.

V5 is the immutable baseline. V6 is the research extension.
This module orchestrates:
  1. Build V6 features from V5 replay output
  2. Calibrate V6 model on train-only slice
  3. Run side-by-side V5 vs V6 validation on untouched OOS
  4. Build forensic verdict

All stages preserve V5 artifacts exactly. No V5 file is modified.
"""

import json
from pathlib import Path

from . import v5_replay, v5_features, v5_model, v5_manifest
from .v6_features import build_features as build_v6_features
from .v6_model import calibrate as calibrate_v6
from .v6_validation import validate as validate_v6
from .v6_verdict import build_verdict as build_v6_verdict

DATA = Path("data")
RESEARCH = DATA / "research"
V5LA = RESEARCH / "v5"
V6LA = RESEARCH / "v6"
V5_LIVE = DATA / "live" / "v5"


def run(model_only=False, log=print):
    """Run V6 pipeline."""
    if not model_only:
        log("[V6] mirror + replay (V5 lineage, immutable) ...")
        v5_replay.mirror_and_replay(log=log)

        log("[V6] build V5 features ...")
        v5_features.build_features(RESEARCH / "v5_features.parquet",
                                   sorted(V5_LIVE.glob("2026*")))

        log("[V6] build V6 features (V5 + enhanced microstructure) ...")
        build_v6_features(RESEARCH / "v6_features.parquet",
                          sorted(V5_LIVE.glob("2026*")))

    log("[V6] calibrate V6 model on train-only slice ...")
    model, cal = calibrate_v6(RESEARCH / "v6_features.parquet", RESEARCH)
    log("      V6 primary R2 (train, h=500): %.4f" % model["500"]["r2_train"])

    log("[V6] side-by-side validation V5 vs V6 ...")
    report = validate_v6(
        RESEARCH / "v5_model.json",
        RESEARCH / "v6_model.json",
        RESEARCH / "v5_features.parquet",
        RESEARCH / "v6_features.parquet",
        out_dir=V6LA,
    )

    log("[V6] build forensic verdict ...")
    verdict = build_v6_verdict(
        RESEARCH / "v5_model.json",
        RESEARCH / "v6_model.json",
        RESEARCH / "v5_features.parquet",
        RESEARCH / "v6_features.parquet",
        out_dir=V6LA,
    )
    return verdict


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-only", action="store_true",
                    help="skip replay/feature build, rerun model+validation only")
    a = ap.parse_args()
    r = run(model_only=a.model_only)
    v = r["verdict"]
    print("\n=== V6 VERDICT: %s ===" % v.get("verdict", v))
    if isinstance(v, dict):
        print("\n".join("- %s" % s for s in v.get("reasons", [])))
    print("\nartifacts: data/research/v6/v6_verdict.json")


if __name__ == "__main__":
    main()
