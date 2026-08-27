"""V5 end-to-end orchestrator — deterministic, staged, honest.

Stages:
  1. mirror raw v2 spans -> data/live/v5 (immutable input)
  2. replay -> derived_v5.jsonl (v4 engine) + integrity gate vs frozen V3
     (feature cols + event keys + frozen-model preds must match event-for-event)
  3. features -> v5_features.parquet (causal, incl. trailing realized vol)
  4. labels -> strict-future forward returns (reused)
  5. model  -> fit ridge ON TRAIN ONLY, freeze v5_model.json (+ calibration)
  6. manifest freeze (before OOS is consumed)
  7. validation + economic report -> verdict (v2_verdict reused)
  8. report: JSON + MD

CLI wiring mirrors v3_run / v4_run.
"""

import argparse
import json
from pathlib import Path

from . import v5_replay, v5_features, v5_model, v5_manifest, v5_economic_report
from .v5_validation import scoreboard, oos_frame
from .v5_cost import measured_gate, total_cost_bps
from .v3_model import load_model as _load_v3

DATA = Path("data")
RESEARCH = DATA / "research"
V5LA = DATA / "research" / "v5"


def run(model_only=False, log=print):
    if not model_only:
        log("[1/8] mirror + replay (v4 engine) ...")
        v5_replay.mirror_and_replay(log=log)
        log("[2/8] integrity gate vs frozen V3 ...")
        fail = v5_replay.integrity_check(log=log)
        if fail:
            raise SystemExit("V5 integrity FAILED: %s" % "; ".join(fail[:5]))
        log("      integrity OK")

    log("[3/8] build features ...")
    v5_features.build_features(RESEARCH / "v5_features.parquet",
                               sorted((DATA / "live" / "v5").glob("2026*")))

    log("[4/8] calibrate model on train-only slice ...")
    model, cal = v5_model.calibrate(RESEARCH / "v5_features.parquet",
                                    out_dir=RESEARCH)
    log("      primary R2 (train, h=500): %.4f" % model["500"]["r2_train"])

    log("[5/8] freeze manifest (before OOS) ...")
    v5_manifest.build_manifest(V5LA)
    vi = v5_manifest.verify(V5LA)
    log("      freeze_id=%s verified=%s" % (vi["frozen_id"], vi["verified"]))

    log("[6/8] validation on untouched OOS ...")
    df, oos_spl = oos_frame(RESEARCH / "v5_features.parquet", model)
    h = model["primary_horizon_ms"]
    from .v5_model import predict
    pred = predict(model, df, h)
    from .v5_economic_report import build_report
    report = build_report(RESEARCH / "v5_features.parquet",
                          RESEARCH / "v5_model.json",
                          "data/hist/research/execution_calibration.json",
                          V5LA, log=log)
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-only", action="store_true",
                    help="skip replay/integrity (rerun model+report only)")
    a = ap.parse_args()
    r = run(model_only=a.model_only, log=print)
    v = r["verdict"]
    print("\n=== V5 VERDICT: %s ===" % (v.get("verdict", v) if isinstance(v, dict) else v))
    if isinstance(v, dict):
        print("\n".join("- %s" % s for s in v.get("reasons", [])))
    print("\nartifacts: data/research/v5/v5_verdict.md")


if __name__ == "__main__":
    main()