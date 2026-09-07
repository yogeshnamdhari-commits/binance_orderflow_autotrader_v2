"""Autonomous research/paper runtime coordinator.

The coordinator deliberately depends on injected components rather than making
exchange/model assumptions. This makes replay, paper, and future authenticated
adapters share the same decision/risk path. Live execution is rejected unless
an explicit, independently supplied live adapter is provided and governance
allows it.
"""
from dataclasses import dataclass, field
from enum import Enum
import time


class RuntimeMode(str, Enum):
    REPLAY = "replay"
    PAPER = "paper"
    TESTNET = "testnet"
    LIVE = "live"


@dataclass(frozen=True)
class RuntimeConfig:
    mode: RuntimeMode = RuntimeMode.PAPER
    symbol: str = "BTCUSDT"
    stale_ms: int = 2000
    max_spread_bps: float = 5.0
    live_authorized: bool = False


@dataclass
class RuntimeStats:
    events: int = 0
    decisions: int = 0
    rejected: int = 0
    submitted: int = 0
    errors: int = 0
    last_event_ms: int = 0
    last_error: str = ""


@dataclass
class RuntimeResult:
    action: str
    reason: str
    decision: object | None = None
    execution: object | None = None


class AutonomousRuntime:
    """One-event-at-a-time coordinator with fail-closed safety semantics.

    Injected components:
      decision_engine.evaluate(features, book_state_str, book)
      risk_engine.pre_trade(...)
      execution.submit(symbol, side, qty, price, client_id=..., book=...)

    The runtime never calls a real exchange itself. A live adapter must be
    explicitly injected and runtime config must have live_authorized=True.
    """

    def __init__(self, cfg: RuntimeConfig, *, decision_engine, risk_engine,
                 execution, journal=None, clock_ms=None):
        self.cfg = cfg
        self.decision_engine = decision_engine
        self.risk_engine = risk_engine
        self.execution = execution
        self.journal = journal
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self.stats = RuntimeStats()
        self.halted = False
        self.halt_reason = ""
        self._sequence = 0

        if cfg.mode == RuntimeMode.LIVE and not cfg.live_authorized:
            raise RuntimeError("LIVE runtime requires explicit authorization")
        if cfg.stale_ms <= 0 or cfg.max_spread_bps <= 0:
            raise ValueError("invalid runtime limits")

    def _emit(self, record):
        if self.journal is None:
            return
        try:
            if hasattr(self.journal, "write"):
                self.journal.write(record)
            elif callable(self.journal):
                self.journal(record)
        except Exception:
            # Runtime observability must not turn a safe decision into a trade.
            pass

    def halt(self, reason):
        self.halted = True
        self.halt_reason = reason or "runtime halted"
        if hasattr(self.risk_engine, "trigger_emergency"):
            self.risk_engine.trigger_emergency(self.halt_reason)
        self._emit({"event": "RUNTIME_HALTED", "reason": self.halt_reason})

    def on_market_event(self, *, features, book, connected=True,
                        equity=0.0, stop_price=None, qty=None):
        """Process one already-normalized market snapshot.

        ``features`` must be causally available at the supplied event time.
        The coordinator does not manufacture features or future labels.
        """
        self.stats.events += 1
        now = self.clock_ms()
        book_state = getattr(features, "book_state", None)
        last_event = getattr(getattr(book, "state", None), "last_event_ms", 0)
        self.stats.last_event_ms = last_event or now

        if self.halted:
            self.stats.rejected += 1
            return RuntimeResult("NO_TRADE", self.halt_reason)
        if not connected:
            self.stats.rejected += 1
            return RuntimeResult("NO_TRADE", "market feed disconnected")
        if last_event and now - last_event > self.cfg.stale_ms:
            self.stats.rejected += 1
            return RuntimeResult("NO_TRADE", "stale market data")

        try:
            decision = self.decision_engine.evaluate(
                features, book_state_str=book_state, book=book)
        except Exception as exc:
            self.stats.errors += 1
            self.stats.last_error = repr(exc)
            self.halt("decision engine error")
            return RuntimeResult("NO_TRADE", "decision engine error")

        self.stats.decisions += 1
        if not getattr(decision, "tradable", False):
            self.stats.rejected += 1
            self._emit({"event": "NO_TRADE", "reason": getattr(decision, "reason", "not tradable")})
            return RuntimeResult("NO_TRADE", getattr(decision, "reason", "not tradable"), decision)

        side = getattr(decision, "side", None)
        spread = float(getattr(features, "spread_bps", 0.0) or 0.0)
        if spread <= 0 or spread > self.cfg.max_spread_bps:
            self.stats.rejected += 1
            return RuntimeResult("NO_TRADE", "spread gate", decision)

        if qty is None:
            # The strategy may supply a risk-sized quantity via a richer risk
            # adapter. Never infer a live quantity from a missing input.
            self.stats.rejected += 1
            return RuntimeResult("NO_TRADE", "quantity not supplied", decision)
        if stop_price is None:
            self.stats.rejected += 1
            return RuntimeResult("NO_TRADE", "stop price not supplied", decision)

        mid = getattr(features, "mid", None)
        if mid is None or mid <= 0:
            self.stats.rejected += 1
            return RuntimeResult("NO_TRADE", "invalid entry price", decision)

        try:
            rd = self.risk_engine.pre_trade(
                equity=equity,
                entry=mid,
                stop=stop_price,
                spread_bps=spread,
                last_event_ms=last_event,
                now_ms=now,
                connected=connected,
                new_notional=abs(qty * mid),
                open_orders=len(getattr(getattr(self.execution, "manager", None), "open_orders", [])),
            )
        except Exception as exc:
            self.stats.errors += 1
            self.stats.last_error = repr(exc)
            self.halt("risk engine error")
            return RuntimeResult("NO_TRADE", "risk engine error", decision)

        if not getattr(rd, "allowed", False):
            self.stats.rejected += 1
            return RuntimeResult("NO_TRADE", getattr(rd, "reason", "risk rejected"), decision)

        client_id = f"{self.cfg.symbol}-{now}-{self._sequence}"
        self._sequence += 1
        try:
            result = self.execution.submit(
                self.cfg.symbol, side, qty, mid, client_id=client_id, book=book)
        except Exception as exc:
            self.stats.errors += 1
            self.stats.last_error = repr(exc)
            self.halt("execution adapter error")
            return RuntimeResult("NO_TRADE", "execution adapter error", decision)

        self.stats.submitted += 1
        self._emit({"event": "EXECUTION", "client_id": client_id,
                    "mode": self.cfg.mode.value, "side": side,
                    "qty": qty, "result": getattr(result, "status", str(result))})
        return RuntimeResult("SUBMITTED", "execution accepted", decision, result)
