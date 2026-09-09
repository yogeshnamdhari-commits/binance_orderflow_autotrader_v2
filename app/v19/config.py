from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ALLOWED_FEATURES = (
    "queue_imbalance_1",
    "queue_imbalance_3",
    "ofi_1",
    "ofi_3",
    "signed_trade_flow",
    "spread_bps",
    "depth_concentration",
    "queue_change_intensity",
    "liquidity_state",
)


@dataclass(frozen=True)
class V19Config:
    symbol: str
    prediction_horizon_ms: int
    feature_names: tuple[str, ...]
    min_train_events: int
    min_test_events: int
    embargo_events: int
    max_feature_age_ms: int
    maker_round_trip_cost_bps: float
    taker_round_trip_cost_bps: float
    non_fill_opportunity_cost_bps: float
    maker_share: float
    cost_stress_multipliers: tuple[float, ...]
    live_order_submission: bool
    config_hash: str


def _canonical_payload(raw: dict[str, Any]) -> dict[str, Any]:
    payload = dict(raw)
    payload.pop("config_hash", None)
    return payload


def load_v19_config(path: Path) -> V19Config:
    raw = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "symbol", "prediction_horizon_ms", "feature_names", "min_train_events",
        "min_test_events", "embargo_events", "max_feature_age_ms",
        "maker_round_trip_cost_bps", "taker_round_trip_cost_bps",
        "non_fill_opportunity_cost_bps", "maker_share", "cost_stress_multipliers",
        "live_order_submission",
    }
    missing = sorted(required.difference(raw))
    if missing:
        raise ValueError(f"missing V19 configuration fields: {', '.join(missing)}")
    features = tuple(str(x) for x in raw["feature_names"])
    unknown = sorted(set(features).difference(ALLOWED_FEATURES))
    if unknown:
        raise ValueError(f"unknown V19 feature names: {', '.join(unknown)}")
    if not features:
        raise ValueError("feature_names must not be empty")
    if int(raw["prediction_horizon_ms"]) <= 0:
        raise ValueError("prediction_horizon_ms must be positive")
    if int(raw["min_train_events"]) <= 0 or int(raw["min_test_events"]) <= 0:
        raise ValueError("sample thresholds must be positive")
    if int(raw["embargo_events"]) < 0:
        raise ValueError("embargo_events must be non-negative")
    if int(raw["max_feature_age_ms"]) < 0:
        raise ValueError("max_feature_age_ms must be non-negative")
    costs = [float(raw[k]) for k in ("maker_round_trip_cost_bps", "taker_round_trip_cost_bps", "non_fill_opportunity_cost_bps")]
    if any(x < 0 for x in costs):
        raise ValueError("execution costs must be non-negative")
    maker_share = float(raw["maker_share"])
    if not 0.0 <= maker_share <= 1.0:
        raise ValueError("maker_share must be in [0, 1]")
    stress = tuple(float(x) for x in raw["cost_stress_multipliers"])
    if not stress or any(x <= 0 for x in stress):
        raise ValueError("cost_stress_multipliers must contain positive values")
    if bool(raw["live_order_submission"]):
        raise ValueError("V19 research configuration cannot enable live order submission")

    canonical = json.dumps(_canonical_payload(raw), sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    supplied = raw.get("config_hash")
    if supplied is not None and supplied != digest:
        raise ValueError("V19 config_hash does not match canonical configuration")
    return V19Config(
        symbol=str(raw["symbol"]),
        prediction_horizon_ms=int(raw["prediction_horizon_ms"]),
        feature_names=features,
        min_train_events=int(raw["min_train_events"]),
        min_test_events=int(raw["min_test_events"]),
        embargo_events=int(raw["embargo_events"]),
        max_feature_age_ms=int(raw["max_feature_age_ms"]),
        maker_round_trip_cost_bps=costs[0],
        taker_round_trip_cost_bps=costs[1],
        non_fill_opportunity_cost_bps=costs[2],
        maker_share=maker_share,
        cost_stress_multipliers=stress,
        live_order_submission=False,
        config_hash=digest,
    )
