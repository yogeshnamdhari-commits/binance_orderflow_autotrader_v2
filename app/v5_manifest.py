"""V5 freeze manifest — locks code + frozen model + measured calibration +
immutable raw spans before the untouched OOS window is evaluated.

freeze_id = sha256 over {modules, artifacts (v5_model / calibration / measured
execution cal / v3 frozen model used for integrity), source hashes, deps}.
The OOS runner (v5_run) recomputes body hashes and aborts unless the id
reproduces. `freeze_only` must run before OOS results are trusted.
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

V5_MODULES = [
    "app/v5_replay.py", "app/v5_features.py", "app/v5_labels.py",
    "app/v5_model.py", "app/v5_cost.py", "app/v5_validation.py",
    "app/v5_economic_report.py", "app/v5_manifest.py", "app/v5_run.py",
    # reused frozen lineage modules
    "app/v3_collector.py", "app/v3_replay.py", "app/v4_replay.py",
    "app/v3_features.py", "app/v3_labels.py", "app/v3_model.py",
    "app/v3_cost.py", "app/v2_verdict.py",
    "app/l2_collector.py", "app/l2_replay.py", "app/orderbook.py",
    "app/models.py", "app/config.py",
]

V5_ARTIFACTS = [
    "data/research/v5_model.json",
    "data/research/v5_calibration.json",
    "data/research/v3_model.json",          # integrity reference
    "data/hist/research/execution_calibration.json",  # measured cost
]


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def module_hashes(root=os.getcwd()):
    out = {}
    for rel in V5_MODULES:
        p = Path(root) / rel
        if p.exists():
            out[rel] = _sha256(p)
    return out


def artifact_hashes():
    out = {}
    for rel in V5_ARTIFACTS:
        p = Path(rel)
        if p.exists():
            out[rel] = _sha256(p)
    return out


def raw_span_hashes():
    out = {}
    root = Path("data/live/v5")
    if root.exists():
        for sd in sorted(root.glob("2026*")):
            raw = sd / "raw.jsonl"
            if raw.exists():
                rel = str(raw)
                if rel not in out:
                    out[rel] = _sha256(raw)
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
            "raw_spans": raw_span_hashes(), "dependencies": deps()}
    freeze_id = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    manifest = {"freeze_id": freeze_id,
                "frozen_at": datetime.now(timezone.utc).isoformat(),
                "run_kind": run_kind,
                "body": body,
                "note": ("V5 freeze_id = sha256(modules+artifacts+raw_spans+deps). "
                         "OOS runner must reproduce it or it aborts.")}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "v5_manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


def verify(out_dir):
    p = Path(out_dir) / "v5_manifest.json"
    if not p.exists():
        return {"verified": False, "reason": "no manifest"}
    prev = json.load(open(p))
    body = prev["body"]
    body["modules"] = module_hashes()
    body["artifacts"] = artifact_hashes()
    body["raw_spans"] = raw_span_hashes()
    body["dependencies"] = deps()
    cur = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return {"verified": cur == prev["freeze_id"], "frozen_id": prev["freeze_id"],
            "current_id": cur,
            "frozen_at": prev.get("frozen_at"),
            "dirty_modules": [k for k, v in prev["body"]["modules"].items()
                              if body["modules"].get(k) != v],
            "dirty_artifacts": [k for k, v in prev["body"]["artifacts"].items()
                                if body["artifacts"].get(k) != v],
            "dirty_raw": [k for k, v in prev["body"]["raw_spans"].items()
                          if body["raw_spans"].get(k) != v]}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/research/v5")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--freeze", action="store_true")
    a = ap.parse_args()
    if a.verify:
        print(json.dumps(verify(a.out), indent=1))
    else:
        print(json.dumps(build_manifest(a.out, run_kind="cmd"), indent=1)[:400])