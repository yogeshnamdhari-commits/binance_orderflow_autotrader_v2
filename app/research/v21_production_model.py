"""Frozen V21 production model inference.

The live path loads a JSON model bundle produced by scripts/v21_model_bundle.py.
The bundle contains only frozen numeric parameters: feature order, scaler
parameters, logistic coefficients, and Huber coefficients. No training occurs
inside the live process.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Duplicated here deliberately so the live process does not import the
# research dataset builder (and therefore does not require pandas/parquet).
V21_V21_FEATURES = (
    "queue_imbalance",
    "microprice_edge_bps",
    "ofi_100ms",
    "ofi_500ms",
    "ofi_1000ms",
    "trade_imbalance_100ms",
    "trade_imbalance_500ms",
    "trade_imbalance_1000ms",
    "trade_intensity_notional_s",
    "spread_bps",
    "mid_return_100ms_bps",
    "mid_return_500ms_bps",
    "depth_5_imbalance",
)


@dataclass(frozen=True)
class V21Prediction:
    p_move: float
    p_up: float
    abs_move_bps: float
    expected_signed_move_bps: float
    toxicity_buy_bps: float
    toxicity_sell_bps: float


class V21ModelBundle:
    """Immutable inference-only representation of a frozen V21 model."""

    SCHEMA_VERSION = 1

    def __init__(self, payload: dict):
        if int(payload.get("schema_version", -1)) != self.SCHEMA_VERSION:
            raise ValueError("unsupported_v21_model_bundle_schema")
        features = list(payload.get("features", []))
        if features != list(V21_FEATURES):
            raise ValueError("v21_feature_order_mismatch")
        self.payload = payload
        self.features = tuple(features)
        self.bundle_sha256 = str(payload.get("bundle_sha256", ""))
        self._validate()

    @staticmethod
    def _finite_vector(obj: dict, key: str, n: int) -> np.ndarray:
        values = obj.get(key)
        if not isinstance(values, list) or len(values) != n:
            raise ValueError(f"invalid_model_vector:{key}")
        arr = np.asarray(values, dtype=float)
        if not np.all(np.isfinite(arr)):
            raise ValueError(f"nonfinite_model_vector:{key}")
        return arr

    @staticmethod
    def _finite_scalar(obj: dict, key: str) -> float:
        value = float(obj[key])
        if not math.isfinite(value):
            raise ValueError(f"nonfinite_model_scalar:{key}")
        return value

    def _validate_logit(self, obj: dict, name: str) -> None:
        self._finite_vector(obj, "mean", len(V21_FEATURES))
        scale = self._finite_vector(obj, "scale", len(V21_FEATURES))
        if np.any(scale <= 0):
            raise ValueError(f"invalid_model_scale:{name}")
        self._finite_vector(obj, "coef", len(V21_FEATURES))
        self._finite_scalar(obj, "intercept")

    def _validate_huber(self, obj: dict, name: str) -> None:
        self._finite_vector(obj, "coef", len(V21_FEATURES))
        self._finite_scalar(obj, "intercept")

    def _validate(self) -> None:
        self._validate_logit(self.payload["move"], "move")
        self._validate_logit(self.payload["direction"], "direction")
        self._validate_huber(self.payload["magnitude"], "magnitude")
        self._validate_huber(self.payload["toxicity_buy"], "toxicity_buy")
        self._validate_huber(self.payload["toxicity_sell"], "toxicity_sell")

    @classmethod
    def from_file(cls, path: str | Path) -> "V21ModelBundle":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        expected = payload.get("bundle_sha256")
        if not expected:
            raise ValueError("v21_model_bundle_hash_required")
        canonical = dict(payload)
        canonical.pop("bundle_sha256", None)
        raw = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected:
            raise ValueError("v21_model_bundle_sha256_mismatch")
        return cls(payload)

    @staticmethod
    def _logit_probability(obj: dict, x: np.ndarray) -> float:
        mean = np.asarray(obj["mean"], dtype=float)
        scale = np.asarray(obj["scale"], dtype=float)
        coef = np.asarray(obj["coef"], dtype=float)
        intercept = float(obj["intercept"])
        z = intercept + float(np.dot((x - mean) / scale, coef))
        z = max(-60.0, min(60.0, z))
        return 1.0 / (1.0 + math.exp(-z))

    @staticmethod
    def _huber_predict(obj: dict, x: np.ndarray) -> float:
        return float(obj["intercept"]) + float(np.dot(np.asarray(obj["coef"], dtype=float), x))

    def predict(self, x: np.ndarray | list[float]) -> V21Prediction:
        arr = np.asarray(x, dtype=float).reshape(-1)
        if len(arr) != len(V21_FEATURES) or not np.all(np.isfinite(arr)):
            raise ValueError("invalid_v21_feature_vector")
        p_move = self._logit_probability(self.payload["move"], arr)
        p_up = self._logit_probability(self.payload["direction"], arr)
        abs_move = max(0.0, self._huber_predict(self.payload["magnitude"], arr))
        expected = p_move * (2.0 * p_up - 1.0) * abs_move
        tox_buy = max(0.0, self._huber_predict(self.payload["toxicity_buy"], arr))
        tox_sell = max(0.0, self._huber_predict(self.payload["toxicity_sell"], arr))
        return V21Prediction(
            p_move=p_move,
            p_up=p_up,
            abs_move_bps=abs_move,
            expected_signed_move_bps=expected,
            toxicity_buy_bps=tox_buy,
            toxicity_sell_bps=tox_sell,
        )
