"""V3 freeze manifest — locks code + artifacts + deps before OOS is consumed.

freeze_id = sha256 over {modules, artifacts, dependencies}. The OOS runner
recomputes the body hashes and must reproduce this freeze_id or it aborts.
Run `freeze_only` before any OOS window is opened.
"""

import hashlib
import json
import os
import sys
from pathlib import Path

V3_MODULES = [
    "app/v3_collector.py", "app/v3_replay.py", "app/v3_features.py",
    "app/v3_labels.py", "app/v3_model.py", "app/v3_cost.py",
    "app/v3_signal.py", "app/v3_validation.py", "app/v3_economic_report.py",
    "app/v3_manifest.py",
    "app/l2_collector.py", "app/l2_replay.py", "app/orderbook.py",
    "app/models.py", "app/config.py",
]

V3_ARTIFACTS = [
    "data/research/v3_model.json",
    "data/research/v3_calibration.json",
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
    for rel in V3_MODULES:
        p = Path(root) / rel
        if p.exists():
            out[rel] = _sha256(p)
    return out


def artifact_hashes():
    out = {}
    for rel in V3_ARTIFACTS:
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
    body = {"modules": module_hashes(root), "artifacts": artifact_hashes(),
            "dependencies": deps()}
    freeze_id = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return {"freeze_id": freeze_id,
            "frozen_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc).isoformat(),
            "run_kind": run_kind, "body": body,
            "note": ("V3 freeze_id = sha256 over modules+artifacts+deps. OOS "
                     "runner must reproduce this id or it aborts.")}


def verify_free(manifest):
    cur = build_manifest(Path(manifest.get("out_dir", ".")), run_kind="verify")
    return {"modules_match": cur["body"]["modules"] == manifest["body"]["modules"],
            "artifacts_match": cur["body"]["artifacts"] == manifest["body"]["artifacts"],
            "deps_match": cur["body"]["dependencies"] == manifest["body"]["dependencies"],
            "freeze_id_match": cur["freeze_id"] == manifest["freeze_id"]}


def freeze_only(out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    m = build_manifest(out_dir, run_kind="freeze")
    m["out_dir"] = str(out_dir)
    path = out_dir / "V3_OOS_MANIFEST.json"
    path.write_text(json.dumps(m, indent=1))
    return m, path


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("data/research"))
    a = ap.parse_args()
    m, p = freeze_only(a.out)
    print("freeze_id:", m["freeze_id"])
    print("manifest:", p)