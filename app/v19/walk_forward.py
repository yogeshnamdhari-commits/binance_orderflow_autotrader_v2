from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .config import V19Config
from .execution import expected_net_pnl, simulate_realized_fill
from .models import fit_return_model, fit_fill_model


@dataclass(frozen=True)
class Split:
    train: tuple[int, ...]
    test: tuple[int, ...]


@dataclass(frozen=True)
class FoldResult:
    timestamps_ns: tuple[int, ...]
    predicted_return_bps: tuple[float, ...]
    fill_probability: tuple[float, ...]
    expected_net_bps: tuple[float, ...]
    realized_net_bps: tuple[float, ...]
    regime_ids: tuple[int, ...]


def make_purged_splits(
    timestamps_ns: Sequence[int],
    train_size: int,
    test_size: int,
    embargo_events: int,
) -> list[Split]:
    if train_size <= 0 or test_size <= 0 or embargo_events < 0:
        raise ValueError("split sizes must be positive and embargo non-negative")
    if any(timestamps_ns[i] > timestamps_ns[i + 1] for i in range(len(timestamps_ns) - 1)):
        raise ValueError("timestamps must be sorted chronologically")

    splits: list[Split] = []
    start = 0
    n = len(timestamps_ns)

    while start + train_size + embargo_events + test_size <= n:
        train_end = start + train_size
        test_start = train_end + embargo_events
        test_end = test_start + test_size
        splits.append(Split(tuple(range(start, train_end)), tuple(range(test_start, test_end))))
        start = test_start

    if not splits:
        raise ValueError("not enough events for one purged split")

    return splits


def evaluate_fold(
    X: np.ndarray,
    forward_returns_bps: Sequence[float],
    fills: Sequence[int],
    timestamps_ns: Sequence[int],
    split: Split,
    config: V19Config,
) -> FoldResult:
    X = np.asarray(X, dtype=float)
    returns = np.asarray(forward_returns_bps, dtype=float)
    fill = np.asarray(fills, dtype=int)
    timestamps = np.asarray(timestamps_ns, dtype=int)

    if X.ndim != 2 or len(X) != len(returns) or len(X) != len(fill) or len(X) != len(timestamps):
        raise ValueError("X, returns, fills and timestamps must be aligned")
    if not np.isfinite(X).all() or not np.isfinite(returns).all():
        raise ValueError("evaluation inputs must be finite")

    names = list(config.feature_names)
    if X.shape[1] != len(names):
        raise ValueError("X columns must match configured feature_names")

    regime_col_idx = names.index("volatility_regime") if "volatility_regime" in names else -1
    if regime_col_idx >= 0:
        regimes = X[:, regime_col_idx].astype(int)
    else:
        regimes = np.ones(len(X), dtype=int)

    if regime_col_idx >= 0:
        X_for_model = np.delete(X, regime_col_idx, axis=1)
        model_feature_names = [n for n in names if n != "volatility_regime"]
    else:
        X_for_model = X
        model_feature_names = names

    train = np.asarray(split.train, dtype=int)
    test = np.asarray(split.test, dtype=int)

    if len(set(train).intersection(test)):
        raise ValueError("train and test observations overlap")
    if max(train) >= min(test):
        raise ValueError("test observations must occur after training observations")

    return_model = fit_return_model(X_for_model[train], returns[train], model_feature_names)
    fill_model = fit_fill_model(X_for_model[train], fill[train], model_feature_names)

    pred = return_model.predict(X_for_model[test])
    probs = np.clip(fill_model.predict_proba(X_for_model[test]), 0.0, 1.0)

    queue_costs = np.zeros(len(test))
    for i, idx in enumerate(test):
        if regimes[idx] == 2:
            queue_costs[i] = 0.3
        elif regimes[idx] == 0:
            queue_costs[i] = 0.1
        else:
            queue_costs[i] = 0.2

    expected = np.asarray([
        expected_net_pnl(
            float(r), float(p),
            config.maker_round_trip_cost_bps,
            config.taker_round_trip_cost_bps,
            config.non_fill_opportunity_cost_bps,
            config.maker_share,
            queue_position_cost_bps=float(queue_costs[i]),
        )
        for i, (r, p) in enumerate(zip(pred, probs))
    ])

    realized = np.asarray([
        simulate_realized_fill(
            float(r), bool(f), config.maker_share >= 0.5,
            config.maker_round_trip_cost_bps,
            config.taker_round_trip_cost_bps,
            partial_fill_ratio=0.95 if regimes[idx] == 2 else 0.98,
        )
        for i, (idx, r, f) in enumerate(zip(test, returns[test], fill[test]))
    ])

    return FoldResult(
        tuple(int(timestamps[i]) for i in test),
        tuple(float(x) for x in pred),
        tuple(float(x) for x in probs),
        tuple(float(x) for x in expected),
        tuple(float(x) for x in realized),
        tuple(int(regimes[i]) for i in test),
    )
