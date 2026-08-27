"""Risk engine — pre-trade and runtime risk controls.

Hard controls (never bypassed by the strategy):
  - daily loss limit         (halt when daily PnL <= -max_daily_loss)
  - max spread               (no trading in wide spreads)
  - max exposure             (absolute notional cap)
  - portfolio heat           (sum of open risk vs equity cap)
  - max drawdown             (halt on drawdown beyond limit)
  - stale-data guard         (no trading on stale book)
  - connection guard         (no trading while disconnected)
  - order-rejection guard    (cooldown after repeated rejections)
  - emergency shutdown       (global kill switch)

Position sizing uses inverse-fractional risk: qty = equity*risk_per_trade / |entry-stop|.
"""

from dataclasses import dataclass, field


@dataclass
class RiskDecision:
    allowed: bool
    qty: float
    reason: str
    details: dict = field(default_factory=dict)


class RiskEngine:
    def __init__(self, risk_per_trade=0.0025, max_daily_loss=0.02,
                 max_spread_bps=5.0, max_exposure_notional=500_000.0,
                 max_portfolio_heat=0.05, max_drawdown_bps=200.0,
                 stale_ms=2000, max_rejections=5, rejection_cooldown_s=60,
                 max_open_orders=10):
        self.risk_per_trade = risk_per_trade
        # NOTE: max_daily_loss default kept broad; real bound enforced via config.assert_safe().
        self.max_daily_loss = max_daily_loss
        self.max_spread_bps = max_spread_bps
        self.max_exposure_notional = max_exposure_notional
        self.max_portfolio_heat = max_portfolio_heat
        self.max_drawdown_bps = max_drawdown_bps
        self.stale_ms = stale_ms
        self.max_rejections = max_rejections
        self.rejection_cooldown_s = rejection_cooldown_s
        self.max_open_orders = max_open_orders
        # runtime state
        self.daily_pnl = 0.0
        self.peak_equity = None
        self.current_exposure = 0.0
        self.open_risk = 0.0
        self.rejections = 0
        self._last_rejection_ts = 0.0
        self.emergency = False
        self.emergency_reason = ""

    # ---- sizing ----
    def size(self, equity, entry, stop, daily_pnl_pct=None, spread_bps=None):
        """Inverse-fractional position sizing. Returns qty (base units)."""
        if daily_pnl_pct is not None and daily_pnl_pct <= -self.max_daily_loss:
            return RiskDecision(False, 0.0, "daily loss limit",
                                {"daily_pnl_pct": daily_pnl_pct})
        if spread_bps is not None and spread_bps > self.max_spread_bps:
            return RiskDecision(False, 0.0, "spread too wide",
                                {"spread_bps": spread_bps})
        d = abs(entry - stop)
        if d <= 0 or entry <= 0:
            return RiskDecision(False, 0.0, "invalid stop", {"entry": entry, "stop": stop})
        qty = equity * self.risk_per_trade / d
        return RiskDecision(True, qty, "risk gate passed",
                            {"risk_per_trade": self.risk_per_trade, "stop_dist": d})

    # ---- guards ----
    def check_stale(self, last_event_ms, now_ms):
        if last_event_ms is None or last_event_ms <= 0:
            return False, "no book data yet"
        if now_ms - last_event_ms > self.stale_ms:
            return False, "stale book data (%d ms)" % (now_ms - last_event_ms)
        return True, "fresh"

    def check_connection(self, connected):
        return (True, "connected") if connected else (False, "disconnected")

    def check_emergency(self):
        return (not self.emergency, self.emergency_reason or "ok")

    def exposure_ok(self, new_notional, equity):
        if new_notional > self.max_exposure_notional:
            return False, "exposure cap exceeded"
        if equity > 0 and self.open_risk / equity > self.max_portfolio_heat:
            return False, "portfolio heat exceeded"
        return True, "exposure ok"

    def check_concurrent(self, open_orders):
        if open_orders >= self.max_open_orders:
            return False, "max concurrent orders (%d) reached" % self.max_open_orders
        return True, "concurrent ok"

    def handle_rejection(self, order_id, now_s, reason="rejected"):
        self.rejections += 1
        self._last_rejection_ts = now_s
        return self.rejections

    def rejection_cooldown_active(self, now_s):
        if self.rejections >= self.max_rejections:
            if now_s - self._last_rejection_ts < self.rejection_cooldown_s:
                return True
            self.rejections = 0  # cooldown elapsed, reset
        return False

    def trigger_emergency(self, reason="manual"):
        self.emergency = True
        self.emergency_reason = reason
        return self.emergency

    def record_fill(self, pnl_bps, notional, equity=None):
        self.daily_pnl += notional * pnl_bps / 1e4
        if equity is not None:
            if self.peak_equity is None or equity > self.peak_equity:
                self.peak_equity = equity
        return self.daily_pnl

    def drawdown_bps(self, equity):
        if self.peak_equity is None or self.peak_equity <= 0 or equity is None:
            return 0.0
        return max(0.0, (self.peak_equity - equity) / self.peak_equity * 1e4)

    def pre_trade(self, equity, entry, stop, spread_bps, last_event_ms, now_ms,
                  connected, new_notional=0.0, daily_pnl_pct=None, open_orders=0):
        """Single composite pre-trade risk gate. All must pass."""
        details = {}
        ok, r = self.check_emergency()
        if not ok:
            return RiskDecision(False, 0.0, "EMERGENCY: %s" % r, details)
        ok, r = self.check_connection(connected)
        if not ok:
            return RiskDecision(False, 0.0, r, details)
        ok, r = self.check_stale(last_event_ms, now_ms)
        if not ok:
            return RiskDecision(False, 0.0, r, details)
        if self.rejection_cooldown_active(now_ms / 1000.0):
            return RiskDecision(False, 0.0, "order-rejection cooldown active", details)
        dd = self.drawdown_bps(equity)
        if dd > self.max_drawdown_bps:
            return RiskDecision(False, 0.0, "max drawdown exceeded (%.1f bps)" % dd, details)
        ok, r = self.exposure_ok(new_notional, equity)
        if not ok:
            return RiskDecision(False, 0.0, r, details)
        ok, r = self.check_concurrent(open_orders)
        if not ok:
            return RiskDecision(False, 0.0, r, details)
        sd = self.size(equity, entry, stop, daily_pnl_pct, spread_bps)
        if not sd.allowed:
            return RiskDecision(False, 0.0, sd.reason, {**details, **sd.details})
        return RiskDecision(True, sd.qty, "PASS", {**details, **sd.details,
                                                  "drawdown_bps": round(dd, 2)})

    def reset(self):
        """Clean runtime state for a safe restart (no positions carried over)."""
        self.daily_pnl = 0.0
        self.peak_equity = None
        self.current_exposure = 0.0
        self.open_risk = 0.0
        self.rejections = 0
        self._last_rejection_ts = 0.0
        self.emergency = False
        self.emergency_reason = ""
