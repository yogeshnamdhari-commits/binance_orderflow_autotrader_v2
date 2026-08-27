"""V2 freeze manifest (Task 7).

Computes immutable version IDs (sha256) over every piece that must be locked
before the untouched-OOS window is opened:

  - all V2 application modules (code)
  - the frozen model/calibration artifacts
  - the execution-cost calibration
  - dependency versions present in the frozen environment

The manifest freeze_id is a hash over all entries. V2_OOS_MANIFEST.json is
written by `--freeze-only` BEFORE any OOS data is consumed; the OOS runner
verifies the same content hashes before evaluating, and will refuse to run the
OOS a second time once consumed (unless --force).
"""

import hashlib
import json
import os
import sys
from pathlib import Path

FZE_MODULES = [
    "app/v2_features.py", "app/v2_labels.py", "app/v2_model.py",
    "app/v2_cost_gate.py", "app/v2_signal.py", "app/v2_validation.py",
    "app/v2_robustness.py", "app/v2_verdict.py", "app/v2_data_integrity.py",
    "app/v2_economic_report.py", "app/v2_manifest.py",
    "app/v2_horizon_diag.py",
    "app/l2_collector.py", "app/l2_replay.py",
    "app/orderbook.py", "app/models.py", "app/config.py",
]

FZE_ARTIFACTS = [
    "data/hist/research/v2_model.json",
    "data/hist/research/v2_calibration.json",
    "data/hist/research/execution_calibration.json",
]


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def module_hashes(root=os.getcwd()):
    out = {}
    for rel in FZE_MODULES:
        p = Path(root) / rel
        if p.exists():
            out[rel] = _sha256(p)
    return out


def artifact_hashes():
    out = {}
    for rel in FZE_ARTIFACTS:
        p = Path(rel)
        if p.exists():
            out[rel] = _sha256(p)
    return out


def deps():
    import importlib.metadata as md
    names = ["numpy", "pandas", "pyarrow", "requests", "websocket-client",
             "python-dotenv", "pytest"]
    out = {}
    for n in names:
        try:
            out[n] = md.version(n)
        except md.PackageNotFoundError:
            out[n] = "missing"
    out["python"] = sys.version.split()[0]
    return out


def build_manifest(out_dir, root=os.getcwd(), run_kind="freeze"):
    mh = module_hashes(root)
    ah = artifact_hashes()
    deps_v = deps()
    body = {"modules": mh, "artifacts": ah, "dependencies": deps_v}
    freeze_id = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return {
        "freeze_id": freeze_id,
        "frozen_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(),
        "run_kind": run_kind,
        "body": body,
        "note": (
            "freeze_id = sha256 over modules+artifacts+deps. The OOS runner "
            "recomputes body hashes and must match this freeze_id or it aborts."),
    }


def verify_free(manifest):
    cur = build_manifest(Path(manifest.get("out_dir", ".")), run_kind="verify")
    return {
        "modules_match": cur["body"]["modules"] == manifest["body"]["modules"],
        "artifacts_match": cur["body"]["artifacts"] == manifest["body"]["artifacts"],
        "deps_match": cur["body"]["dependencies"] == manifest["body"]["dependencies"],
        "freeze_id_match": cur["freeze_id"] == manifest["freeze_id"],
    }


def freeze_only(out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    m = build_manifest(out_dir, run_kind="freeze")
    m["out_dir"] = str(out_dir)
    path = out_dir / "V2_OOS_MANIFEST.json"
    path.write_text(json.dumps(m, indent=1))
    return m, path


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("data/hist/research"))
    a = ap.parse_args()
    m, p = freeze_only(a.out)
    print("freeze_id:", m["freeze_id"])
    print("manifest:", p)