from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ALLOWED_FEATURE_FAMILIES = frozenset({
    "v16_control",
    "liquidation",
    "funding_basis",
    "cross_market",
})


@dataclass(frozen=True)
class V18Config:
    symbol: str
    prediction_horizon_ms: int
    feature_families: tuple[str, ...]
    min_train_events: int
    min_test_events: int
    max_feature_age_ms: int
    cost_stress_multipliers: tuple[float, ...]
    live_order_submission: bool
    config_hash: str


def _canonical_payload(raw: dict[str, Any]) -> dict[str, Any]:
    payload = dict(raw)
    payload.pop("config_hash", None)
    return payload


def load_v18_config(path: Path) -> V18Config:
    raw = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "symbol",
        "prediction_horizon_ms",
        "feature_families",
        "min_train_events",
        "min_test_events",
        "max_feature_age_ms",
        "cost_stress_multipliers",
        "live_order_submission",
    }
    missing = sorted(required.difference(raw))
    if missing:
        raise ValueError(f"missing V18 configuration fields: {', '.join(missing)}")

    families = tuple(raw["feature_families"])
    unknown = sorted(set(families).difference(_ALLOWED_FEATURE_FAMILIES))
    if unknown:
        raise ValueError(f"unknown V18 feature families: {', '.join(unknown)}")
    if raw["prediction_horizon_ms"] <= 0:
        raise ValueError("prediction_horizon_ms must be positive")
    if raw["min_train_events"] <= 0 or raw["min_test_events"] <= 0:
        raise ValueError("sample thresholds must be positive")
    if raw["max_feature_age_ms"] < 0:
        raise ValueError("max_feature_age_ms must be non-negative")
    if not raw["cost_stress_multipliers"] or any(x <= 0 for x in raw["cost_stress_multipliers"]):
        raise ValueError("cost_stress_multipliers must contain positive values")
    if bool(raw["live_order_submission"]):
        raise ValueError("V18 research configuration cannot enable live order submission")

    canonical = json.dumps(_canonical_payload(raw), sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    supplied = raw.get("config_hash")
    if supplied is not None and supplied != digest:
        raise ValueError("V18 config_hash does not match canonical configuration")

    return V18Config(
        symbol=str(raw["symbol"]),
        prediction_horizon_ms=int(raw["prediction_horizon_ms"]),
        feature_families=families,
        min_train_events=int(raw["min_train_events"]),
        min_test_events=int(raw["min_test_events"]),
        max_feature_age_ms=int(raw["max_feature_age_ms"]),
        cost_stress_multipliers=tuple(float(x) for x in raw["cost_stress_multipliers"]),
        live_order_submission=False,
        config_hash=digest,
    )
