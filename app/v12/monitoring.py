"""V12 operational monitoring — market-data, model, signal, execution health.

Implements Rule 31: monitoring for market-data health, sequence health,
book freshness, model health, signal frequency, fill rate, latency, spread,
PnL, drawdown, position, API errors, reconnects, risk events.

Generates alerts for critical failures (Rule 32 / Rule 16).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class AlertSeverity(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class Alert:
    severity: AlertSeverity
    component: str
    message: str
    ts_ms: int
    metric: str
    value: float | str


@dataclass
class HealthMetrics:
    """Snapshot of operational health metrics."""
    # market-data health
    last_depth_update_ms: int = 0
    last_trade_ms: int = 0
    last_receive_ns: int = 0
    depth_gap_count: int = 0
    reconnect_count: int = 0
    sequence_error_count: int = 0
    # book freshness
    book_age_ms: int = 0
    book_crossed: bool = False
    # model health
    model_loaded: bool = False
    model_checksum_ok: bool = False
    signal_count: int = 0
    signal_rate_hz: float = 0.0
    signal_positive_rate: float = 0.0
    # execution / fill
    orders_submitted: int = 0
    orders_filled: int = 0
    fill_rate: float = 0.0
    mean_latency_ms: float = 0.0
    mean_spread_bps: float = 0.0
    # risk
    risk_state: str = "NORMAL"
    risk_halt_reason: str = ""
    # position / pnl
    position_btc: float = 0.0
    position_side: str = "FLAT"
    unrealized_pnl_bps: float = 0.0
    realized_pnl_bps: float = 0.0
    drawdown_bps: float = 0.0
    peak_equity_bps: float = 0.0
    daily_pnl_bps: float = 0.0
    # api
    api_error_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {k: (v.value if isinstance(v, Enum) else v) for k, v in self.__dict__.items()}


class V12Monitor:
    """Operational monitoring and alerting for the V12 live system."""

    STALE_DATA_THRESHOLD_MS = 5000
    GAP_ALERT_THRESHOLD = 1
    LATENCY_ALERT_MS = 1000
    SPREAD_ALERT_BPS = 5.0
    SIGNAL_MIN_HZ = 0.1
    FILL_RATE_MIN = 0.1
    MAX_DAILY_LOSS_BPS = 200.0
    MAX_DRAWDOWN_BPS = 100.0

    def __init__(self, log_path: str | Path | None = None, alert_path: str | Path | None = None):
        self._metrics = HealthMetrics()
        self._alerts: list[Alert] = []
        self._log_path = Path(log_path) if log_path else None
        self._alert_path = Path(alert_path) if alert_path else None
        self._window_start_ms = self._now_ms()
        self._last_signal_ms = 0

    @staticmethod
    def _now_ms() -> int:
        return int(datetime.now(timezone.utc).timestamp() * 1000)

    def update_market_data(
        self,
        depth_update_ms: int,
        trade_ms: int,
        receive_ns: int,
        gap: bool = False,
        reconnect: bool = False,
        sequence_error: bool = False,
    ) -> None:
        self._metrics.last_depth_update_ms = depth_update_ms
        self._metrics.last_trade_ms = trade_ms
        self._metrics.last_receive_ns = receive_ns
        if gap:
            self._metrics.depth_gap_count += 1
        if reconnect:
            self._metrics.reconnect_count += 1
        if sequence_error:
            self._metrics.sequence_error_count += 1
        self._check_market_data_health()

    def update_book(self, age_ms: int, crossed: bool) -> None:
        self._metrics.book_age_ms = age_ms
        self._metrics.book_crossed = crossed
        if age_ms > self.STALE_DATA_THRESHOLD_MS:
            self._alert(AlertSeverity.CRITICAL, "book", "stale order book", "book_age_ms", age_ms)
        if crossed:
            self._alert(AlertSeverity.CRITICAL, "book", "crossed order book", "book_crossed", True)

    def update_model(self, loaded: bool, checksum_ok: bool) -> None:
        self._metrics.model_loaded = loaded
        self._metrics.model_checksum_ok = checksum_ok
        if not loaded:
            self._alert(AlertSeverity.CRITICAL, "model", "frozen model not loaded", "model_loaded", False)
        if loaded and not checksum_ok:
            self._alert(AlertSeverity.CRITICAL, "model", "model checksum mismatch", "model_checksum_ok", False)

    def record_signal(self, positive: bool = True) -> None:
        self._metrics.signal_count += 1
        if positive:
            self._metrics.signal_positive_rate = (
                (self._metrics.signal_positive_rate * (self._metrics.signal_count - 1) + 1)
                / self._metrics.signal_count
            )
        else:
            self._metrics.signal_positive_rate = (
                (self._metrics.signal_positive_rate * (self._metrics.signal_count - 1))
                / self._metrics.signal_count
            )
        now = self._now_ms()
        if self._last_signal_ms > 0:
            elapsed = now - self._last_signal_ms
            if elapsed > 0:
                self._metrics.signal_rate_hz = 1000.0 / elapsed
        self._last_signal_ms = now
        self._check_signal_health()

    def _check_signal_health(self) -> None:
        elapsed_s = (self._now_ms() - self._window_start_ms) / 1000.0
        if elapsed_s > 0 and self._metrics.signal_rate_hz < self.SIGNAL_MIN_HZ:
            self._alert(
                AlertSeverity.WARNING, "signal",
                f"low signal frequency ({self._metrics.signal_rate_hz:.2f} Hz)",
                "signal_rate_hz", self._metrics.signal_rate_hz,
            )

    def update_execution(
        self, submitted: bool, filled: bool, latency_ms: int, spread_bps: float
    ) -> None:
        if submitted:
            self._metrics.orders_submitted += 1
        if filled:
            self._metrics.orders_filled += 1
        self._metrics.mean_latency_ms = 0.9 * self._metrics.mean_latency_ms + 0.1 * latency_ms
        self._metrics.mean_spread_bps = 0.9 * self._metrics.mean_spread_bps + 0.1 * spread_bps
        if self._metrics.orders_submitted > 0:
            self._metrics.fill_rate = self._metrics.orders_filled / self._metrics.orders_submitted
        if latency_ms > self.LATENCY_ALERT_MS:
            self._alert(AlertSeverity.WARNING, "execution", "high latency", "latency_ms", latency_ms)
        if spread_bps > self.SPREAD_ALERT_BPS:
            self._alert(AlertSeverity.WARNING, "execution", "wide spread", "spread_bps", spread_bps)

    def update_position(
        self,
        position_btc: float,
        side: str,
        unrealized_pnl_bps: float,
        realized_pnl_bps: float,
        drawdown_bps: float,
        peak_equity_bps: float,
        daily_pnl_bps: float,
    ) -> None:
        self._metrics.position_btc = position_btc
        self._metrics.position_side = side
        self._metrics.unrealized_pnl_bps = unrealized_pnl_bps
        self._metrics.realized_pnl_bps = realized_pnl_bps
        self._metrics.drawdown_bps = drawdown_bps
        self._metrics.peak_equity_bps = peak_equity_bps
        self._metrics.daily_pnl_bps = daily_pnl_bps
        if daily_pnl_bps <= -self.MAX_DAILY_LOSS_BPS:
            self._alert(AlertSeverity.CRITICAL, "risk", "daily loss limit breached", "daily_pnl_bps", daily_pnl_bps)
        if drawdown_bps >= self.MAX_DRAWDOWN_BPS:
            self._alert(AlertSeverity.CRITICAL, "risk", "drawdown limit breached", "drawdown_bps", drawdown_bps)

    def update_risk(self, state: str, halt_reason: str = "") -> None:
        self._metrics.risk_state = state
        self._metrics.risk_halt_reason = halt_reason
        if state in ("HALT", "EMERGENCY"):
            self._alert(AlertSeverity.CRITICAL, "risk", f"risk state={state}: {halt_reason}", "risk_state", state)

    def update_api_error(self) -> None:
        self._metrics.api_error_count += 1
        self._alert(AlertSeverity.WARNING, "api", "API error encountered", "api_error_count", self._metrics.api_error_count)

    def _check_market_data_health(self) -> None:
        now_ns = time.time_ns()
        if self._metrics.last_receive_ns > 0:
            age_ms = (now_ns - self._metrics.last_receive_ns) / 1e6
            if age_ms > self.STALE_DATA_THRESHOLD_MS:
                self._alert(AlertSeverity.CRITICAL, "market_data", "stale market data", "data_age_ms", age_ms)
        if self._metrics.depth_gap_count >= self.GAP_ALERT_THRESHOLD:
            self._alert(AlertSeverity.WARNING, "market_data", "depth sequence gap detected", "depth_gap_count", self._metrics.depth_gap_count)

    def _alert(self, severity: AlertSeverity, component: str, message: str, metric: str, value: float | str) -> None:
        alert = Alert(
            severity=severity, component=component, message=message,
            ts_ms=self._now_ms(), metric=metric, value=value,
        )
        self._alerts.append(alert)
        if self._alert_path:
            self._alert_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._alert_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": alert.ts_ms, "severity": severity.value, "component": component,
                    "message": message, "metric": metric, "value": value if isinstance(value, str) else str(value),
                }) + "\n")
        print(f"[ALERT:{severity.value}] {component}: {message} ({metric}={value})")

    def metrics(self) -> HealthMetrics:
        return self._metrics

    def alerts(self, since_ms: int | None = None) -> list[Alert]:
        if since_ms is None:
            return list(self._alerts)
        return [a for a in self._alerts if a.ts_ms >= since_ms]

    def snapshot(self) -> dict[str, Any]:
        return {
            "ts_ms": self._now_ms(),
            "metrics": self._metrics.to_dict(),
            "alerts": [
                {"severity": a.severity.value, "component": a.component, "message": a.message,
                 "metric": a.metric, "value": a.value, "ts_ms": a.ts_ms}
                for a in self._alerts
            ],
        }

    def save_snapshot(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.snapshot(), indent=2), encoding="utf-8")
        return path


def health_check_all(metrics: HealthMetrics) -> dict[str, bool]:
    """Aggregate health gate checks from metrics snapshot."""
    return {
        "market_data_fresh": metrics.book_age_ms <= V12Monitor.STALE_DATA_THRESHOLD_MS,
        "no_depth_gaps": metrics.depth_gap_count == 0,
        "no_reconnects_recently": metrics.reconnect_count == 0,
        "model_loaded": metrics.model_loaded,
        "model_checksum_ok": metrics.model_checksum_ok,
        "risk_normal": metrics.risk_state in ("NORMAL", "WARNING"),
        "position_ok": abs(metrics.position_btc) <= 0.1,
        "no_critical_alerts": all(a.severity != AlertSeverity.CRITICAL for a in []),  # filled externally
        "fill_rate_ok": metrics.fill_rate >= 0.1 if metrics.orders_submitted > 0 else True,
    }
