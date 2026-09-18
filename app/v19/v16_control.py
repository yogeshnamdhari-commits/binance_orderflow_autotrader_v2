from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np

from app.v11.parser import V11DataParser
from app.v16.config import V16Config
from app.v16.features import V16_FEATURES, extract_v16_features
from app.v16.model import V16FillProbabilityModel, V16ReturnModel
from app.v16.execution import V16ExecutionSim


def aligned_v16_outcomes(
    session_dir: Path,
    timestamps_ns: Sequence[int],
    *,
    return_model_path: Path = Path("archive/v16/v16_frozen_return_model.joblib"),
    fill_model_path: Path = Path("archive/v16/v16_frozen_fill_model.joblib"),
    max_feature_age_ms: int = 10_000,
) -> np.ndarray:
    """Apply the frozen V16 models to the same causal timestamps as V19.

    This produces the aligned control vector required by the V19 gate rather
    than comparing V19's aggregate mean with an unrelated historical mean.
    A timestamp with no sufficiently recent V16 feature row is treated as a
    no-trade control outcome (0 bps), never as missing or future information.
    """
    if not return_model_path.exists() or not fill_model_path.exists():
        raise FileNotFoundError("frozen V16 model artifacts are required")
    parser = V11DataParser(Path(session_dir))
    books, trades = parser.parse()
    features = extract_v16_features(books, trades, V16Config().feature_window_ms)
    if features.empty:
        raise ValueError("V16 feature extraction produced no observations")

    return_model = V16ReturnModel.load(return_model_path)
    fill_model = V16FillProbabilityModel.load(fill_model_path)
    sim = V16ExecutionSim(V16Config())
    X = features[V16_FEATURES]
    predicted_return = np.asarray(return_model.predict(X), dtype=float)
    fill_probability = np.clip(np.asarray(fill_model.predict_proba(X), dtype=float), 0.0, 1.0)
    decisions = [sim.route(float(r), float(p)) for r, p in zip(predicted_return, fill_probability)]
    outcome_by_ts = {
        int(features.iloc[i]["ts_ms"] * 1_000_000): float(decisions[i].expected_pnl_bps)
        for i in range(len(decisions))
    }
    feature_ts = np.asarray([int(x) for x in outcome_by_ts], dtype=np.int64)
    outcomes = np.zeros(len(timestamps_ns), dtype=float)
    for i, ts_ns in enumerate(timestamps_ns):
        pos = int(np.searchsorted(feature_ts, int(ts_ns), side="right") - 1)
        if pos < 0:
            continue
        feature_time = int(feature_ts[pos])
        age_ms = (int(ts_ns) - feature_time) / 1_000_000.0
        if age_ms <= max_feature_age_ms:
            outcomes[i] = outcome_by_ts[feature_time]
    return outcomes
