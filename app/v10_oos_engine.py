"""Walk-forward passive-order economics using only past-fold estimates."""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Sequence, Tuple

from .v10_execution_economics import PassiveQuote, adverse_selection_bps, passive_order_ev_bps
from .v10_survival import kaplan_meier_fill_probability
from .v10_walkforward import chronological_folds


@dataclass(frozen=True)
class OrderSample:
    timestamp: float
    side: str
    quote_price: float
    mid_at_submit: float
    horizon_ms: float
    filled: bool
    fill_time_ms: float
    mid_at_horizon: float
    maker_fee_bps: float

    def __post_init__(self) -> None:
        if self.timestamp < 0:
            raise ValueError("timestamp must be non-negative")
        if self.horizon_ms <= 0:
            raise ValueError("horizon_ms must be positive")
        if self.fill_time_ms <= 0:
            raise ValueError("fill_time_ms must be positive")
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")


@dataclass(frozen=True)
class OOSFoldResult:
    train_count: int
    test_count: int
    train_fill_probability: float
    train_adverse_selection_bps: float
    predicted_test_ev_bps: float
    realized_test_ev_bps: float


@dataclass(frozen=True)
class OOSEvaluation:
    folds: Tuple[OOSFoldResult, ...]
    mean_realized_ev_bps: float
    ci_low_bps: float
    ci_high_bps: float

    @property
    def economic_gate_pass(self) -> bool:
        return bool(self.folds) and self.ci_low_bps > 0.0


def sample_realized_ev_bps(sample: OrderSample) -> float:
    """Realized per-submission EV; an unfilled order contributes zero."""
    if not sample.filled:
        return 0.0
    quote = PassiveQuote(
        side=sample.side,
        price=sample.quote_price,
        mid=sample.mid_at_submit,
        maker_fee_bps=sample.maker_fee_bps,
    )
    signed_return_bps = (
        (sample.mid_at_horizon - sample.mid_at_submit) / sample.mid_at_submit
        * (10_000.0 if sample.side == "BUY" else -10_000.0)
    )
    half_spread_bps = abs(quote.mid - quote.price) / quote.mid * 10_000.0
    return half_spread_bps + signed_return_bps - quote.maker_fee_bps


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def evaluate_oos_folds(
    samples: Sequence[OrderSample], *, train_size: int = 100, test_size: int = 25, step: int = 25
) -> OOSEvaluation:
    """Estimate execution economics on rolling folds without future leakage."""
    ordered = tuple(sorted(samples, key=lambda s: s.timestamp))
    if not ordered:
        raise ValueError("samples must not be empty")
    horizon = ordered[0].horizon_ms
    if any(s.horizon_ms != horizon for s in ordered):
        raise ValueError("all samples must use the same horizon")

    fold_results = []
    for fold in chronological_folds(ordered, train_size=train_size, test_size=test_size, step=step):
        train = fold.train
        test = fold.test
        km = kaplan_meier_fill_probability(
            [(s.fill_time_ms, s.filled) for s in train], horizon=horizon
        )
        adverse = _mean(
            [
                adverse_selection_bps(s.side, s.mid_at_submit, s.mid_at_horizon)
                for s in train
                if s.filled
            ]
        )
        predicted = _mean(
            [
                passive_order_ev_bps(
                    PassiveQuote(
                        side=s.side,
                        price=s.quote_price,
                        mid=s.mid_at_submit,
                        maker_fee_bps=s.maker_fee_bps,
                    ),
                    fill_probability=km.probability,
                    adverse_selection_cost_bps=max(0.0, adverse),
                )
                for s in test
            ]
        )
        realized = _mean([sample_realized_ev_bps(s) for s in test])
        fold_results.append(
            OOSFoldResult(
                train_count=len(train),
                test_count=len(test),
                train_fill_probability=km.probability,
                train_adverse_selection_bps=adverse,
                predicted_test_ev_bps=predicted,
                realized_test_ev_bps=realized,
            )
        )

    realized = [f.realized_test_ev_bps for f in fold_results]
    mean_ev = _mean(realized)
    if len(realized) > 1:
        variance = sum((x - mean_ev) ** 2 for x in realized) / (len(realized) - 1)
        se = sqrt(variance / len(realized))
    else:
        se = 0.0
    return OOSEvaluation(
        folds=tuple(fold_results),
        mean_realized_ev_bps=mean_ev,
        ci_low_bps=mean_ev - 1.96 * se,
        ci_high_bps=mean_ev + 1.96 * se,
    )
