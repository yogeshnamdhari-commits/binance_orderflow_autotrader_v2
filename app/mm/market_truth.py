"""Canonical market-truth contract.

This module does not manufacture market values. Every field is represented with
source, exchange timestamp (when the source provides one), local receipt time,
freshness and an explicit status. The signal gate is fail-closed: required
fields must be OK, otherwise the symbol is NO_TRADE.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


class TruthStatus(str, Enum):
    OK = "OK"
    STALE = "STALE"
    INVALID = "INVALID"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class MetricTruth:
    value: Any = None
    source: str = ""
    exchange_ts_ms: int | None = None
    receive_ts_ms: int | None = None
    max_age_ms: int | None = None
    status: TruthStatus = TruthStatus.UNAVAILABLE
    reason: str = ""

    @property
    def age_ms(self) -> int | None:
        if self.receive_ts_ms is None or self.exchange_ts_ms is None:
            return None
        return max(0, int(self.receive_ts_ms) - int(self.exchange_ts_ms))

    def fresh(self, now_ms: int) -> bool:
        if self.status != TruthStatus.OK:
            return False
        if self.max_age_ms is None or self.exchange_ts_ms is None:
            return True
        return max(0, int(now_ms) - int(self.exchange_ts_ms)) <= int(self.max_age_ms)


@dataclass
class SymbolTruth:
    symbol: str

    price: MetricTruth = field(default_factory=MetricTruth)
    volume_24h: MetricTruth = field(default_factory=MetricTruth)
    change_24h_pct: MetricTruth = field(default_factory=MetricTruth)

    best_bid: MetricTruth = field(default_factory=MetricTruth)
    best_ask: MetricTruth = field(default_factory=MetricTruth)
    spread_bps: MetricTruth = field(default_factory=MetricTruth)

    mark_price: MetricTruth = field(default_factory=MetricTruth)
    index_price: MetricTruth = field(default_factory=MetricTruth)
    funding_rate: MetricTruth = field(default_factory=MetricTruth)
    open_interest: MetricTruth = field(default_factory=MetricTruth)

    delta: MetricTruth = field(default_factory=MetricTruth)
    cvd: MetricTruth = field(default_factory=MetricTruth)
    buy_volume: MetricTruth = field(default_factory=MetricTruth)
    sell_volume: MetricTruth = field(default_factory=MetricTruth)
    imbalance_l1: MetricTruth = field(default_factory=MetricTruth)
    imbalance_l5: MetricTruth = field(default_factory=MetricTruth)
    imbalance_l10: MetricTruth = field(default_factory=MetricTruth)

    liquidation_notional: MetricTruth = field(default_factory=MetricTruth)
    sweep: MetricTruth = field(default_factory=MetricTruth)
    fvg: MetricTruth = field(default_factory=MetricTruth)
    regime: MetricTruth = field(default_factory=MetricTruth)

    signal: MetricTruth = field(default_factory=MetricTruth)
    signal_authority: str = "DATA_GATE"
    signal_reason: str = ""

    book_sequence_ok: bool = False
    book_synchronized: bool = False
    trade_stream_ok: bool = False
    market_stream_ok: bool = False

    def required_metrics(self) -> dict[str, MetricTruth]:
        return {
            "price": self.price,
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "mark_price": self.mark_price,
            "index_price": self.index_price,
            "funding_rate": self.funding_rate,
            "open_interest": self.open_interest,
            "delta": self.delta,
            "cvd": self.cvd,
            "imbalance_l1": self.imbalance_l1,
            "imbalance_l5": self.imbalance_l5,
            "imbalance_l10": self.imbalance_l10,
        }

    def gate(self, now_ms: int, required: Iterable[str] | None = None) -> tuple[bool, tuple[str, ...]]:
        names = list(required) if required is not None else list(self.required_metrics())
        reasons: list[str] = []

        if not self.book_synchronized:
            reasons.append("BOOK_NOT_SYNCHRONIZED")
        if not self.book_sequence_ok:
            reasons.append("BOOK_SEQUENCE_INVALID")
        if not self.trade_stream_ok:
            reasons.append("TRADE_STREAM_INVALID")
        if not self.market_stream_ok:
            reasons.append("MARKET_STREAM_INVALID")

        for name in names:
            metric = getattr(self, name)
            if metric.status != TruthStatus.OK:
                reasons.append(f"{name.upper()}_{metric.status.value}")
            elif not metric.fresh(now_ms):
                reasons.append(f"{name.upper()}_STALE")

        return (not reasons, tuple(reasons))

    def force_no_trade(self, now_ms: int, reason: str) -> None:
        self.signal = MetricTruth(
            value="NO_TRADE",
            source="DATA_GATE",
            receive_ts_ms=now_ms,
            status=TruthStatus.OK,
            reason=reason,
        )
        self.signal_authority = "DATA_GATE"
        self.signal_reason = reason

    def flatten(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "symbol": self.symbol,
            "signal_authority": self.signal_authority,
            "signal_reason": self.signal_reason,
            "book_sequence_ok": self.book_sequence_ok,
            "book_synchronized": self.book_synchronized,
            "trade_stream_ok": self.trade_stream_ok,
            "market_stream_ok": self.market_stream_ok,
        }
        for name, metric in self.required_metrics().items():
            row[name] = metric.value
            row[f"{name}_source"] = metric.source
            row[f"{name}_exchange_ts_ms"] = metric.exchange_ts_ms
            row[f"{name}_receive_ts_ms"] = metric.receive_ts_ms
            row[f"{name}_status"] = metric.status.value
            row[f"{name}_reason"] = metric.reason
        row["signal"] = self.signal.value
        row["signal_status"] = self.signal.status.value
        return row


def ok_metric(
    value: Any,
    *,
    source: str,
    exchange_ts_ms: int | None,
    receive_ts_ms: int,
    max_age_ms: int | None,
) -> MetricTruth:
    return MetricTruth(
        value=value,
        source=source,
        exchange_ts_ms=exchange_ts_ms,
        receive_ts_ms=receive_ts_ms,
        max_age_ms=max_age_ms,
        status=TruthStatus.OK,
    )


def unavailable(source: str, reason: str) -> MetricTruth:
    return MetricTruth(
        value=None,
        source=source,
        status=TruthStatus.UNAVAILABLE,
        reason=reason,
    )


def invalid(source: str, reason: str) -> MetricTruth:
    return MetricTruth(
        value=None,
        source=source,
        status=TruthStatus.INVALID,
        reason=reason,
    )
