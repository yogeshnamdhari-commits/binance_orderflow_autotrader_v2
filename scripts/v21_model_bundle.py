"""Freeze V21 learned models into a portable production JSON bundle.

The bundle contains no training data and no executable model objects. It is an
explicit, hashable inference artifact whose feature order and training scope
are recorded. Live processes must only load this bundle; they must never fit
models.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import pandas as pd

from scripts.v21_learned_market_maker import _build_models
from scripts.v21_orderflow_dataset import FEATURES


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _logit_payload(pipe) -> dict:
    scale = pipe.named_steps["scale"]
    logit = pipe.named_steps["logit"]
    return {
        "mean": [float(x) for x in scale.mean_],
        "scale": [float(x) for x in scale.scale_],
        "coef": [float(x) for x in logit.coef_[0]],
        "intercept": float(logit.intercept_[0]),
    }


def _huber_payload(model) -> dict:
    return {
        "coef": [float(x) for x in model.coef_],
        "intercept": float(model.intercept_),
    }


def freeze(dataset_path: Path, toxicity_path: Path, sessions: list[str], output: Path) -> dict:
    dataset = pd.read_parquet(dataset_path)
    toxicity = pd.read_parquet(toxicity_path)
    available = sorted(dataset["session"].unique().tolist())
    unknown = sorted(set(sessions) - set(available))
    if unknown:
        raise ValueError(f"unknown_training_sessions:{unknown}")
    if not sessions:
        raise ValueError("empty_training_session_set")

    models, sizes = _build_models(dataset, toxicity, sessions)
    payload = {
        "schema_version": 1,
        "source_commit": os.getenv("RESEARCH_COMMIT_SHA", os.getenv("GITHUB_SHA", "")),
        "model_family": "v21_two_stage_orderflow_mm",
        "horizon_ms": 250,
        "features": list(FEATURES),
        "training_sessions": list(sessions),
        "training_sizes": sizes,
        "dataset_sha256": sha256_file(dataset_path),
        "toxicity_dataset_sha256": sha256_file(toxicity_path),
        "move": _logit_payload(models.move),
        "direction": _logit_payload(models.direction),
        "magnitude": _huber_payload(models.magnitude),
        "toxicity_buy": _huber_payload(models.toxicity_buy),
        "toxicity_sell": _huber_payload(models.toxicity_sell),
        "production_inference": {
            "training_in_live_process": False,
            "feature_order_locked": True,
            "online_scaling": "frozen_training_mean_and_scale",
            "economic_signal_horizon_ms": 250,
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["bundle_sha256"] = hashlib.sha256(canonical).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--toxicity", type=Path, required=True)
    parser.add_argument("--sessions", required=True, help="comma-separated session ids used for the frozen production fit")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sessions = [x for x in (s.strip() for s in args.sessions.split(",")) if x]
    report = freeze(args.dataset, args.toxicity, sessions, args.output)
    print(json.dumps({
        "status": "FROZEN",
        "bundle_sha256": report["bundle_sha256"],
        "training_sessions": report["training_sessions"],
        "training_sizes": report["training_sizes"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
