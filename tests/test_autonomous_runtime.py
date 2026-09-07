from types import SimpleNamespace
import pytest

from app.autonomous_runtime import AutonomousRuntime, RuntimeConfig, RuntimeMode


class Decision:
    def __init__(self, tradable=True, side="BUY", reason="ok"):
        self.tradable = tradable
        self.side = side
        self.reason = reason


class DecisionEngine:
    def __init__(self, decision=None, error=False):
        self.decision = decision or Decision()
        self.error = error

    def evaluate(self, *args, **kwargs):
        if self.error:
            raise RuntimeError("boom")
        return self.decision


class Risk:
    def __init__(self, allowed=True):
        self.allowed = allowed
        self.emergency = False

    def pre_trade(self, **kwargs):
        return SimpleNamespace(allowed=self.allowed, reason="RISK_PASS" if self.allowed else "risk")

    def trigger_emergency(self, reason):
        self.emergency = True


class Execution:
    def __init__(self):
        self.calls = []
        self.manager = SimpleNamespace(open_orders=[])

    def submit(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return SimpleNamespace(status="PAPER_FILLED")


class Book:
    state = SimpleNamespace(last_event_ms=1000)


@pytest.fixture
def features():
    return SimpleNamespace(book_state="BOOK_VALID", spread_bps=1.0, mid=100000.0)


def make_runtime(decision=None, risk=None, execution=None, mode=RuntimeMode.PAPER, clock=1100):
    return AutonomousRuntime(
        RuntimeConfig(mode=mode, stale_ms=2000, max_spread_bps=5.0),
        decision_engine=DecisionEngine(decision),
        risk_engine=risk or Risk(),
        execution=execution or Execution(),
        clock_ms=lambda: clock,
    )


def test_live_requires_explicit_authorization():
    with pytest.raises(RuntimeError):
        make_runtime(mode=RuntimeMode.LIVE)


def test_nontradable_decision_never_reaches_execution(features):
    execution = Execution()
    rt = make_runtime(Decision(False, reason="cost"), execution=execution)
    result = rt.on_market_event(features=features, book=Book(), equity=10000, stop_price=99900, qty=0.01)
    assert result.action == "NO_TRADE"
    assert execution.calls == []


def test_stale_market_data_blocks_execution(features):
    execution = Execution()
    rt = make_runtime(execution=execution, clock=5000)
    result = rt.on_market_event(features=features, book=Book(), equity=10000, stop_price=99900, qty=0.01)
    assert result.action == "NO_TRADE"
    assert "stale" in result.reason
    assert execution.calls == []


def test_risk_failure_blocks_execution(features):
    execution = Execution()
    rt = make_runtime(risk=Risk(False), execution=execution)
    result = rt.on_market_event(features=features, book=Book(), equity=10000, stop_price=99900, qty=0.01)
    assert result.action == "NO_TRADE"
    assert execution.calls == []


def test_missing_quantity_blocks_execution(features):
    execution = Execution()
    rt = make_runtime(execution=execution)
    result = rt.on_market_event(features=features, book=Book(), equity=10000, stop_price=99900)
    assert result.action == "NO_TRADE"
    assert "quantity" in result.reason
    assert execution.calls == []


def test_accepted_paper_decision_reaches_adapter(features):
    execution = Execution()
    rt = make_runtime(execution=execution)
    result = rt.on_market_event(features=features, book=Book(), equity=10000, stop_price=99900, qty=0.01)
    assert result.action == "SUBMITTED"
    assert result.execution.status == "PAPER_FILLED"
    assert len(execution.calls) == 1


def test_decision_exception_halts_runtime(features):
    rt = AutonomousRuntime(
        RuntimeConfig(), decision_engine=DecisionEngine(error=True),
        risk_engine=Risk(), execution=Execution(), clock_ms=lambda: 1100)
    result = rt.on_market_event(features=features, book=Book(), equity=10000, stop_price=99900, qty=0.01)
    assert result.action == "NO_TRADE"
    assert rt.halted is True
    assert rt.risk_engine.emergency is True
